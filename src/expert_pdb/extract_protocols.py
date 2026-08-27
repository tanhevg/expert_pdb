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

from .util import (
    ollama_requests,
    polars as upl,
    util,
    jats
)

from expert_pdb.download_publications import STATE_FILENAME, configure_logging, read_mapping
PROMPT = """
    You are an expert curator of biochemical data. Below is an academic publication in JATS format that contains 
    information about recombinant cloning, expression and purification of proteins (protein production).
    Read the publication and return only the sections and paragraphs that describe protein production. Please take 
    care to copy the relevant text as is, without making any changes, additions or omissions. 
    Please be specific, and ignore the other experimental protocols that you might come across in the paper, such as crystallization,
    structure determination, target selection and others. Return the full sections or paragraphs, including the opening and closing JATS tags. 
    The protocol string should include at least one `sec` tag with the preserved `id` attribute. If the section contains other paragraphs,
    not relevant for protein production protocol, these paragraphs should be dropped. If the protocol is described in multiple sections, all sections should be included.
    
    The result should be returned in JSON format. Return a top-level JSON array of records matching the supplied JSON schema. Do not add prose or
    markdown. In the unlikely scenario when the relevant protocol text cannot be located, return an empty JSON array.
    
    The publication might describe a complex molecule containing multiple protein chains. For such publications the JSON 
    should contain multiple records, each describing the protocols for a single protein. The identifiers for the protein should be included in the relevant field.
    The protein might be identified by multiple ids, for example gene name, Uniprot id, etc. The source of the id should be preserved, along with the id itself. 
    Sometimes gene names are agreed upon by convention, and it is impossible to identify the bioinformatics database where the gene name is coming from. 
    In this case, just leave 'source=gene_name'. Sometimes it is not possible to state where the id is coming from at all. In this case, just leave 'source=unknown'. 
    
    The protocol text might contain just a reference to cited papers or to supplementary materials. Such protocols should also be preserved.

    Record fields:
    - `protocol`: The protein production protocol text from the publication.
      - Example: <sec id="sec42"><title>Protein expression and purification</title><p>The proteins were expressed in E. Coli ...</p></sec>
    - `protein_identifiers`. A list of objects with id and type. 
      - Example1: [{"id": "ARRDC3", "source": "HGNC"}, {"id": "Q96B67", "source": "Uniprot"}, {"id": "QWERTY_12345", "source": "unknown"}]
      - Example2: [{"id": "omcT", "source": "gene_name"}, {"id": "Q74A87", "source": "Uniprot"}]
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
# PROTOCOL_SCHEMA: dict[str, pl.DataType] = {
#     "pdb_id": pl.String,
#     "pmcid": pl.String,
#     "source_file": pl.String,
#     "source_format": pl.String,
#     "protocol_text": pl.String,
#     "status": pl.String,
#     "evidence_locators": pl.List(pl.String),
#     "deferred_source_info": pl.String,
# }

PROTOCOL_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "protocol": {"type": "string"},
            "protein_identifiers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "source": {"type": "string"}},
                    "required": ["id", "source"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["protocol", "protein_identifiers"],
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
    parser.add_argument("--store-prompts", action="store_true", help="Store prompts.")
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

def process_publication(publication: dict[str, Any], run_dir:Path, args:argparse.Namespace):
    download_version:str = publication["download_version"]
    pmcid = publication["pmcid"]
    target_dir = args.target_dir
    capture_stats = args.stats_df_parquet is not None
    base_url = args.ollama_url
    model = args.ollama_model
    log.info(f"Extracting protocols from {download_version}")
    # publication_dir = target_dir / "publications" / download_version
    # assert publication_dir.is_dir()
    # jats_data = jats.jats_to_json(publication_dir)
    jats_file = target_dir / "publications" / download_version / f"{download_version}.xml"
    # jats_xml = jats_file.read_text()
    jats_xml = jats.compact_jats(jats_file)
    prompt = build_detector_prompt(jats_xml)
    if args.store_prompts:
        out_path = run_dir/ f"{pmcid}_prompt.txt"
        log.info(f"Writing prompt of size {len(prompt)} to {out_path}")
        with out_path.open('w') as f:
            f.write(prompt)
    response = ollama_requests.ollama_json(
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
        ollama_requests.preflight_ollama(args.ollama_url)
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
        stats_schema = STATS_SCHEMA | {k:pl.Int64 for k in ollama_requests.STATS_KEYS}
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
            protocols_json = process_publication(publication, run_dir, args)
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
