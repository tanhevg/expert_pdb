"""Extract Expert protein-production records from downloaded PMC JATS packages."""

import argparse
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import requests

from .util import polars as upl
from .util import ollama
from .util import util

from expert_pdb.download_publications import STATE_FILENAME, configure_logging, read_mapping
PROMPT = """
    You are an expert curator of biochemical data. Read the publication below, and extract from it any 
    information about protein cloning, expression and purification protocols. Please be specific, and 
    ignore the other experimental protocols that you might come across in the paper, such as crystallisation,
    structure determination, target selection and others.
    
    Return a top-level JSON array of records matching the supplied JSON schema. Do not add prose or
    markdown. Note that some of the fields are optional.
    
    The publication might describe a complex molecule containing multiple protein chains. For such publications the json 
    should contain multiple records, each describing the protocols for a single protein. 
    
    The protocols might be scattered across the publication in different sections and paragraphs. 
    There is no need to preserve the paper structure in such cases, multiple paragraphs can just be concatenated, but the 
    section ids should be preserved in the `protocol_locator` field.

    Never try to edit the publication text. All paragraphs from the publication should be included as is, only changing
    JATS formatting to markdown where possible. Do not try to remove bits of text that you think are irrelevant
    or repetitive. Repeating the same protocol for different proteins that are described in the same publication is fine.

    All references that are cited in the protocols should be preserved in the `references` field.

    Record fields:
    - `state`: One of `missing`, `retrieved`, `supplement`, `citation`.
      - `missing` means the publication does not contain any protocols of interest.
      - `retrieved` means that the protocols were retrieved from this publication.
      - `supplement` means that the protocols are contained in supplementary material.
      - `citation` means that the protocols are contained in one of the cited papers.
    - `protocol_text`: only present if `state=retrieved`. The protocol text from the publication. 
    The publication text must be left unchanged, but JATS formatting should be replaced with markdown formatting.
    - `protocol_locator`: only present if `state=retrieved`. List of JATS section ids where the `protocol_text` was taken from. 
    List of strings. Example: ["S1", "S2", "S7"].
    - `protocol_supplements`: only present if `state=supplement`. JATS ids of the supplements that contains the protocol.
    List of strings. Example: ["SD2"].
    - `protocol_references`: only present if `state=citation`. JATS reference ids of the cited papers with the protocols. 
     List of strings. Example: ["R13", "R42"].
    - `protein_identifiers`. These protein might be identified by multilple ids, for example gene name, uniprot id, etc. These identifiers 
    should be extracted into this field, stating the id source. Sometimes gene names are agreed upon by convention, and it is impossible to 
    identify the bioinformatics database where the gene name is coming from. In this case, just leave 'gene_name'. Sometimes it is not possible to 
    state where the id is coming from at all. In this case, just leave unknown. A list of objects with id and type. 
    Example1: [{"id": "ARRDC3", "source": "HGNC"}, {"id": "Q96B67", "source": "Uniprot"}, {"id": "QWERTY_12345", "source": "unknown"}]
    Example2: [{"id": "omcT", "source": "gene_name"}, {"id": "Q74A87", "source": "Uniprot"}]
    - `references` - list of references that were cited in the protocol text. JATS ids should be preserved.
    If JATS reference contains external ids, like Pubmed ID, PMC ID, or DOI, then give those external ids. Nature citation is not required in this case. 
    If there are no ids, then give a Nature-formatted citation, i.e. authors, title, journal, issue, pages, (year). 
    Give not more than 3 authors, for multiple authors use _et al_.
    A list of objects, with fields dictated by what is present in JATS. 
    Example1: [{"id": "R1", "PMID": "7816639", "PMCID": "PMC11370360", "DOI": "10.1101/2024.08.14.607690"}, 
        {"id": "R7", "PMID": "7815639", "PMCID": "PMC11470360", "DOI": "10.1101/2024.08.14.687690"}] 
    Example2: [{"id": "R17", "citation": "Smith, J. D. _et al_. Quantum coherence in biological systems. Nature 529, 245-248 (2024)."}]
"""

EXTRACTION_STATE_FILENAME = "extraction_state.parquet"
OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen3.5:27b"

STATE_SCHEMA: dict[str, pl.DataType] = {
    "pmcid": pl.String,
    "download_version": pl.String,
    "status": pl.String,
    "run_id": pl.String,
    "error": pl.String,
    "updated_at": pl.String,
}
PROTOCOL_SCHEMA: dict[str, pl.DataType] = {
    "pdb_id": pl.String,
    "pmcid": pl.String,
    "source_file": pl.String,
    "source_format": pl.String,
    "protocol_text": pl.String,
    "status": pl.String,
    "evidence_locators": pl.List(pl.String),
    "deferred_source_info": pl.String,
}

PROTOCOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "state": {"type": "string", "enum": ["missing", "retrieved", "supplement", "citation"]},
            "protocol_text": {"type": "string"},
            "protocol_locator": {"type": "array", "items": {"type": "string"}},
            "protocol_supplements": {"type": "array", "items": {"type": "string"}},
            "protocol_references": {"type": "array", "items": {"type": "string"}},
            "protein_identifiers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "source": {"type": "string"}},
                    "required": ["id", "source"],
                    "additionalProperties": False,
                },
            },
            "references": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "PMID": {"type": "string"},
                        "PMCID": {"type": "string"}, "DOI": {"type": "string"},
                        "citation": {"type": "string"},
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["state", "protein_identifiers", "references"],
        "additionalProperties": False,
    },
}

STATS_SCHEMA = {
    'pmcid': pl.String,
    'run_id': pl.Int32,
    'llm_runner': pl.String,
    'llm_model': pl.String,
}


log = logging.getLogger(__name__)

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_dir", type=Path, help="Downloader output directory.")
    selected = parser.add_mutually_exclusive_group()
    selected.add_argument("--pdb-ids", nargs="+", metavar="PDB_ID")
    selected.add_argument("--pmc-ids", nargs="+", metavar="PMCID")
    parser.add_argument("--ollama-url", default=OLLAMA_DEFAULT_URL)
    parser.add_argument("--ollama-model", default=OLLAMA_DEFAULT_MODEL)
    parser.add_argument("--stats-df-parquet")
    parser.add_argument("--stats-run-id", type=int, required=False)
    parser.add_argument("--force", action="store_true", help="Re-extract successful publications.")
    return parser.parse_args(argv)


def select_publications(target_dir: Path, args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    mapping_path = target_dir / "pdb_pubmed.csv.gz"
    state_path = target_dir / STATE_FILENAME
    if not mapping_path.exists() or not state_path.exists():
        raise ValueError("target_dir must contain pdb_pubmed.csv.gz and download_state.parquet")
    pdb_pmc_mapping = read_mapping(mapping_path)
    state = pl.read_parquet(state_path)
    required = {"pmid", "pmcid", "download_version", "downloaded"}
    if not required.issubset(state.columns):
        raise ValueError(f"Download state has incompatible columns: {state.columns}")
    linked = pdb_pmc_mapping.join(
        state.select("pmid", "pmcid", "download_version", "downloaded"), on="pmid", how="inner"
    ).filter(pl.col("downloaded") & pl.col("pmcid").is_not_null())
    requested_pdb_ids = util.split_ids(args.pdb_ids)
    requested_pmc_ids = {value.upper() for value in util.split_ids(args.pmc_ids)}
    if requested_pdb_ids:
        linked = linked.filter(pl.col("pdb_id").is_in(sorted(requested_pdb_ids)))
    if requested_pmc_ids:
        linked = linked.filter(pl.col("pmcid").str.to_uppercase().is_in(sorted(requested_pmc_ids)))

    selected: dict[str, dict[str, Any]] = {}
    selected_rows = linked.select("pdb_id", "pmcid", "download_version").unique()
    for row in selected_rows.iter_rows(named=True):
        pmcid = str(row["pmcid"]).upper()
        entry = selected.setdefault(
            pmcid,
            {"pmcid": pmcid, "download_version": row["download_version"], "pdb_ids": []},
        )
        pdb_id = str(row["pdb_id"]).lower()
        if pdb_id not in entry["pdb_ids"]:
            entry["pdb_ids"].append(pdb_id)
    for entry in selected.values():
        entry["pdb_ids"].sort()
    return selected

def build_detector_prompt(jats: str) -> str:
    return PROMPT + "\n\nJSON schema:\n" + json.dumps(PROTOCOL_OUTPUT_SCHEMA) + \
        "\n\nHere is the publication, formatted as JATS XML:\n" + jats

def _successful(state: pl.DataFrame, pmcid: str, version: str) -> bool:
    return (
        state.filter(
            (pl.col("pmcid") == pmcid)
            & (pl.col("download_version") == version)
            & (pl.col("status") == "success")
        ).height
        > 0
    )

def process_publication(
    target_dir: Path, publication: dict[str, Any], base_url: str, model: str, run_dir: Path, capture_stats: bool
):
    download_version:str = publication["download_version"]
    log.info(f"Extracting protocols from {download_version}")
    # publication_dir = target_dir / "publications" / download_version
    # assert publication_dir.is_dir()
    # jats_data = jats.jats_to_json(publication_dir)
    jats_file = target_dir / "publications" / download_version / f"{download_version}.xml"
    jats_xml = jats_file.read_text()
    prompt = build_detector_prompt(jats_xml)
    response = ollama.ollama_json(
        base_url, model, prompt, publication["pmcid"], PROTOCOL_OUTPUT_SCHEMA, run_dir, capture_stats
    )
    log.info(f"Extracted protocols for {len(response)} proteins")
    return response



def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    try:
        publications = select_publications(args.target_dir, args)
    except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
        log.error("Could not select downloaded publications: %s", exc)
        return 1
    if not publications:
        log.error("No downloaded publications matched the selection.")
        return 1
    try:
        ollama.preflight_ollama(args.ollama_url)
    except requests.RequestException as exc:
        log.error("Ollama is unavailable at %s: %s", args.ollama_url, exc)
        return 1

    state_path = args.target_dir / EXTRACTION_STATE_FILENAME
    state = upl.load_or_create_parquet(state_path, STATE_SCHEMA)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    run_dir: Path = args.target_dir / "llm_runs" / run_id
    os.makedirs(run_dir, exist_ok=True)
    capture_stats = args.stats_df_parquet is not None
    if capture_stats:
        assert args.stats_run_id is not None, "Run id is required for capturing stats"
        stats_schema = STATS_SCHEMA | {k:pl.Int64 for k in ollama.STATS_KEYS}
        stats_df_path = Path(args.stats_df_parquet)
        stats_df = upl.load_or_create_parquet(stats_df_path, stats_schema)
        log.info(f"Loaded stats df with shape {stats_df.shape} to {stats_df_path}")
        new_stats_df = []
    for pmcid, publication in sorted(publications.items()):
        version = str(publication["download_version"])
        if not args.force and _successful(state, pmcid, version):
            log.info("Skipping already successful %s (%s)", pmcid, version)
            continue
        try:
            log.info(f"Processing {pmcid}")
            protocols_json = process_publication(
                args.target_dir, publication, args.ollama_url, args.ollama_model, run_dir, capture_stats
            )
            if capture_stats:
                stats = protocols_json[1]
                protocols_json = protocols_json[0]
                new_stats_df.append({'pmcid': pmcid, 'run_id': args.stats_run_id, 'llm_model': args.ollama_model, 'llm_runner': 'ollama'} | stats)
            out_path = run_dir/ f"{pmcid}_protocols.json"
            with out_path.open('w') as f:
                json.dump(protocols_json, f)
            log.info(f"Dumped protocols to {out_path}")
            new_state = [{
                "pmcid": pmcid,
                "download_version": version,
                "status": "success",
                "run_id": run_id,
                "error": None,
                "updated_at": upl.now(),
            }]
        except Exception as exc:
            new_state = [{
                "pmcid": pmcid,
                "download_version": version,
                "status": "failure",
                "run_id": run_id,
                "error": str(type(exc)) + ' : ' + str(exc),
                "updated_at": upl.now(),
            }]
            log.error(f"Exception processing pmc id {pmcid}", exc_info=exc)
        finally:
            state = upl.upsert(state, new_state, key_columns=["pmcid"])
            state.write_parquet(state_path)
    if capture_stats:
        stats_df = pl.concat([stats_df, pl.DataFrame(new_stats_df, schema=stats_schema)])
        log.info(f"Writing stats df with shape {stats_df.shape} to {stats_df_path}")
        stats_df.write_parquet(stats_df_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
