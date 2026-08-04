"""Download PMC publications linked to PDB entries.

The state in ``download_state.parquet`` is deliberately updated throughout the
workflow. Re-running the command with the same target directory resumes both
PMC ID resolution and S3 downloads.
"""

import argparse
import gzip
import logging
import logging.config
import shutil
import zipfile
from pathlib import Path

import polars as pl
import requests
from requests.adapters import HTTPAdapter, Retry

from expert_pdb.pmc_id_resolver import resolve_pmc_id
from expert_pdb.pmc_s3 import (
    download_open_pmc_s3,
    find_latest_version,
    init_s3_client,
    list_open_pmc_versions,
)

log = logging.getLogger(__name__)


PDB_PUBMED_URL = "https://ftp.ebi.ac.uk/pub/databases/msd/sifts/flatfiles/csv/pdb_pubmed.csv.gz"
RESOLUTION_BATCH_SIZE = 200
STATE_FILENAME = "download_state.parquet"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target_dir", type=Path, help="Directory for state and downloads."
    )
    parser.add_argument(
        "--pdb-ids",
        nargs="+",
        metavar="PDB_ID",
        help="Specific PDB IDs to process (for example: 1abc 2def).",
    )
    parser.add_argument(
        "--num-publications",
        dest="num_publications",
        type=int,
        help="Randomly select this many PMIDs.",
    )
    args = parser.parse_args(argv)
    if args.num_publications is not None and args.num_publications <= 0:
        parser.error("--num-publications must be greater than zero")
    if args.pdb_ids and args.num_publications is not None:
        parser.error("--pdb-ids and --num-publications cannot be used together")
    return args


def configure_logging() -> None:
    config_path = Path(__file__).resolve().parents[2] / "log.cfg"
    logging.config.fileConfig(config_path, disable_existing_loggers=False)


def download_mapping(target_dir: Path) -> Path:
    destination = target_dir / "pdb_pubmed.csv.gz"
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    log.info(f"Downloading {PDB_PUBMED_URL}")
    temporary = destination.with_suffix(".csv.gz.part")
    with requests.get(PDB_PUBMED_URL, stream=True, timeout=120) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            shutil.copyfileobj(response.raw, handle)
    temporary.replace(destination)
    return destination


def read_mapping(path: Path) -> pl.DataFrame:
    with gzip.open(path, "rb") as handle:
        mapping = pl.read_csv(handle, comment_prefix="#")
    columns = {column.lower(): column for column in mapping.columns}
    pdb_column = columns.get("pdb_id", columns.get("pdb"))
    pmid_column = columns.get("pubmed_id", columns.get("pmid"))
    if pdb_column is None or pmid_column is None:
        raise ValueError(f"Unexpected PDB-PubMed mapping columns: {mapping.columns}")
    return (
        mapping.select(
            pl.col(pdb_column).cast(pl.String).str.to_lowercase().alias("pdb_id"),
            pl.col(pmid_column).cast(pl.String).alias("pmid"),
        )
        .filter(pl.col("pmid").is_not_null() & (pl.col("pmid") != ""))
        .unique().sort('pmid')
    )


def select_mapping(
    mapping: pl.DataFrame, args: argparse.Namespace, resumed_pmids: list[str] | None = None
) -> pl.DataFrame:
    if args.pdb_ids:
        wanted = [pdb_id.lower() for value in args.pdb_ids for pdb_id in value.split(",")]
        return mapping.filter(pl.col("pdb_id").is_in(wanted))
    if args.num_publications is not None:
        if resumed_pmids is not None:
            return mapping.filter(pl.col("pmid").is_in(resumed_pmids))
        pmids = mapping.select(
            pl.col("pmid").unique().sample(
                n=min(args.num_publications, mapping.get_column("pmid").n_unique()),
                shuffle=True,
            )
        ).get_column("pmid").to_list()
        return mapping.filter(pl.col("pmid").is_in(pmids))
    return mapping


def load_or_create_state(path: Path, mapping: pl.DataFrame) -> pl.DataFrame:
    selected_pmids = mapping.select("pmid").unique()
    if not path.exists():
        ret = selected_pmids.with_columns(
            pl.lit(None, dtype=pl.String).alias("pmcid"),
            pl.lit(False).alias("resolution_attempted"),
            pl.lit(None, dtype=pl.String).alias("download_version"),
            pl.lit(False).alias("downloaded"),
            pl.lit(False).alias("download_checked"),
        )
        ret.write_parquet(path)
        return ret

    existing = pl.read_parquet(path)
    required = {"pmid", "pmcid", "download_version", "downloaded"}
    if not required.issubset(existing.columns):
        raise ValueError(f"Existing state has incompatible columns: {existing.columns}")
    if "resolution_attempted" not in existing.columns:
        existing = existing.with_columns(
            pl.col("pmcid").is_not_null().alias("resolution_attempted")
        )
    if "download_checked" not in existing.columns:
        existing = existing.with_columns(pl.col("downloaded").alias("download_checked"))
    # Preserve progress only for PMIDs selected for this invocation.
    ret = selected_pmids.join(
        existing.unique(subset=["pmid"], keep="first", maintain_order=True),
        on="pmid",
        how="left",
    ).with_columns(
        pl.col("downloaded").fill_null(False)
    )
    return ret

def resolve_pmids(state: pl.DataFrame, state_path: Path) -> pl.DataFrame:
    attempted = set(
        state.filter(pl.col("resolution_attempted")).get_column("pmid")
    )
    unresolved = [pmid for pmid in state.get_column("pmid").unique() if pmid not in attempted]
    log.info(f"Will resolve {len(unresolved)} PMIDs to PMC")
    resolved_count = 0
    for start in range(0, len(unresolved), RESOLUTION_BATCH_SIZE):
        batch = unresolved[start : start + RESOLUTION_BATCH_SIZE]
        pmc_ids = resolve_pmc_id(batch)
        resolved_count += len(pmc_ids)
        remaining = max(0, len(unresolved) - (start + RESOLUTION_BATCH_SIZE))
        log.info(
            "Resolved %s PMIDs to %s PMCIDs; %s to go.",
            start + RESOLUTION_BATCH_SIZE,
            resolved_count,
            remaining,
        )
        state = state.with_columns(
            pl.col("pmid").replace_strict(pmc_ids, default=pl.col("pmcid")).alias("pmcid"),
            pl.col("pmid").is_in(batch).or_(pl.col("resolution_attempted")).alias("resolution_attempted"),
        )
        state.write_parquet(state_path)
    return state


def unzip_archives(publication_dir: Path) -> None:
    for archive in publication_dir.rglob("*.zip"):
        extracted_dir = archive.with_suffix("")
        marker = extracted_dir / ".extracted"
        if marker.exists():
            log.info(f"Not unzipping {archive}")
            continue
        log.info(f"Unzipping {archive}")
        extracted_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as contents:
            for member in contents.infolist():
                destination = (extracted_dir / member.filename).resolve()
                if not destination.is_relative_to(extracted_dir.resolve()):
                    raise ValueError(f"Unsafe ZIP member in {archive}: {member.filename}")
            contents.extractall(extracted_dir)
        marker.touch()

def download_publication(pmcid:str, client, state: pl.DataFrame, state_path: Path, publications_dir: Path):
    completed = state.filter(
        (pl.col("pmcid") == pmcid) & pl.col("download_checked")
    ).height > 0
    if completed:
        return state
    versions = list_open_pmc_versions(client, pmcid)
    latest_version = find_latest_version(versions)
    if latest_version is None:
        state = state.with_columns(
            pl.when(pl.col("pmcid") == pmcid)
            .then(pl.lit(True))
            .otherwise(pl.col("download_checked"))
            .alias("download_checked")
        )
        state.write_parquet(state_path)
        return state
    download_open_pmc_s3(client, latest_version, publications_dir)
    unzip_archives(publications_dir / latest_version)
    state = state.with_columns(
        pl.when(pl.col("pmcid") == pmcid)
        .then(pl.lit(latest_version))
        .otherwise(pl.col("download_version"))
        .alias("download_version"),
        pl.when(pl.col("pmcid") == pmcid)
        .then(pl.lit(True))
        .otherwise(pl.col("downloaded"))
        .alias("downloaded"),
        pl.when(pl.col("pmcid") == pmcid)
        .then(pl.lit(True))
        .otherwise(pl.col("download_checked"))
        .alias("download_checked"),
    )
    state.write_parquet(state_path)
    return state


def download_publications(state: pl.DataFrame, state_path: Path, target_dir: Path) -> pl.DataFrame:
    client = init_s3_client()
    publications_dir = target_dir / "publications"
    pmcids = state.filter(pl.col("pmcid").is_not_null()).get_column("pmcid").unique()
    for i, pmcid in enumerate(pmcids):
        log.info(f"Publication {i} out of {len(pmcids)}")
        try:
            state = download_publication(pmcid, client, state, state_path, publications_dir)
        except Exception as e:
            log.error(f"Error downloading pmcid {pmcid}", exc_info=e)
         
    return state


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    args.target_dir.mkdir(parents=True, exist_ok=True)
    state_path = args.target_dir / STATE_FILENAME
    resumed_pmids = None
    if args.num_publications is not None and state_path.exists():
        resumed_pmids = pl.read_parquet(state_path).get_column("pmid").unique().to_list()
    mapping = select_mapping(
        read_mapping(download_mapping(args.target_dir)), args, resumed_pmids
    )
    if mapping.is_empty():
        log.error("No matching PDB IDs with PubMed records found.")
        return 1
    retries = Retry(total=5, backoff_factor=0.25)
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retries))
    state = load_or_create_state(state_path, mapping)
    state.write_parquet(state_path)
    state = resolve_pmids(state, state_path)
    download_publications(state, state_path, args.target_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
