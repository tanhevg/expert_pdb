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
import asyncio

from ollama._utils import convert_function_to_tool
from ollama import Tool

from . import expert_schema
from .util import agentic_tools, jats, ollama, pdb_sequences, util
from .util import polars as upl

from .download_publications import STATE_FILENAME, configure_logging, read_mapping


EXTRACTION_STATE_FILENAME = "extraction_state.parquet"
OLLAMA_DEFAULT_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen3.8:27b"

STATE_SCHEMA: dict[str, pl.DataType] = {
    "pmcid": pl.String,
    "download_version": pl.String,
    "status": pl.String,
    "run_id": pl.String,
    "error": pl.String,
    "updated_at": pl.String,
}

STATS_SCHEMA = {
    'pmcid': pl.String,
    'run_id': pl.Int32,
    'llm_runner': pl.String,
    'llm_model': pl.String,
}

EXPERT_JSON_SCHEMA = expert_schema.expert_json_schema({
    'O_source': {
        'type': 'array',
        'description': 'content from the publication used to extract Expert data',
        'items': {
            'type': 'object',
            'properties': {
                'publication_text': {
                    'type': 'string',
                    'description': 'Verbatim JATS-formatted excerpt from the publication where the Expert data was extracted from.'
                },
                'locator': {
                    'type': 'string',
                    'description': 'JATS id of the section or the paragraph that the Expert data was extracted from.'
                },
                'reference_ids': {
                    'type': 'array',
                    'description': 'List of references where the protocol is described. Use JATS ids where available.',
                    'items': {
                        'type': 'string'
                    }
                }
            }
        }
    },
    'C_N_tags': {
        'type': 'array',
        'description': 'List of N-terminal tags, in the order that they appear in the sequence',
        'items': {
            'type': 'string'
        }
    },
    'C_C_tags': {
        'type': 'array',
        'description': 'List of C-terminal tags, in the order that they appear in the sequence',
        'items': {
            'type': 'string'
        }
    },
})

PROMPT = """
    You are an expert curator of biochemical data. Below is an academic publication that contains 
    information about recombinant cloning, expression and purification of proteins (protein production).
    Read the publication and extract the information about protein production from it in Expert format, 
    as defined by the schema below. The response should be a valid JSON document.  Populate as many fields as possible.
   
    The PDB protein-chain data below is authoritative deposited construct information. When a
    protocol can be unambiguously associated with a listed PDB ID and chain, populate C2 with
    that chain's exact `sequence`, even when the sequence is absent from the publication text.
    This sequence may include engineered mutations and expression tags. Do not populate C2 from
    a PDB chain when the publication does not establish that the construct is the same one, and
    never infer, extend, trim, or combine sequences. Do not use PDB data to invent any other
    fields. For a construct unambiguously associated with a PDB chain, use that chain's
    `uniprot_mappings` to populate T4. These PDBe UniProt mappings take precedence over any
    UniProt ID inferred from the publication; use an inferred publication ID only when no mapped
    PDBe UniProt ID is available for the matched chain. Each `uniprot_mappings` item gives the
    associated UniProt residue boundaries and coverage. PDBe gene names are supporting identifiers.

    If the publication contains an NCBI protein accession, use the
    `get_cds_for_protein_accession` tool to retrieve its coding sequence and populate C1. For
    other NCBI accession types, do not guess or derive a coding sequence. Use only the portion
    of the genetic sequence that translates to amino acid sequence. Write python code to verify
    that sequence translation is correct.

    If the publication contains production protocols for multiple proteins or construct definitions, 
    the JSON array should contain multiple elements. Be as specific as possible, do not try to 
    represent multiple constructs with the same JSON object. Having multiple JSON objects with 
    duplicated fields is fine. Each construct definition encountered in the text should be 
    represented with an entry in `proteins` array.

    If the publication identifies the target proteins in ways that are not supported by Expert, i.e. not
    HGNC gene names or Uniprot or PDB ids, these additional target ids should be included in the JSON
    as additional fields. These fields should be marked with prefix 'TN_', and the id system, if 
    available. For example, {{... "TN_NCBI_Gene_ID": "1105", "TN_ENSEML_ID": "ENSG00000153922.14" }}.
    Populate HGNC and PDB ids only if they are present in the publication text; do not try to
    hallucinate them. Follow the PDBe mapping rule above for UniProt IDs.

    If the publication descibes a protein complex, populate the 'CX...' fields.

    Populate the PMC id of the publication `PMCID={pmcid}` in the 'O1' field.

    Do not include the completeness score. 

    If the publication does not contain a protein production protocol, return an empty JSON array.
    
    Populate the 'O_source' field with the excerpts from the publication that were used for extracting
    Expert data. Be as specific as possible. If different parts of the paragraph refer to protocols
    for different proteins, only include the relevant part. Populate the deep-most JATS section or paragraph 
    id pertaining to the excerpt. If the data about the protocol is scattered across multiple 
    sections or paragraphs, include multiple elements in the 'O_source' array.

    If for some (or all) of the proteins the protocol is specified only as a reference to supplementary material
    or a cited paper, then include those protein identifiers and `O_source`, skipping all other fields.
    Include the reference ids in `O_source.reference_ids`. Try to be as specific as possible, and mention
    only the references pertaining to the specific protein.

    The buffer strings should be formatted specifically, mentioning the pH, the buffer, and for 
    each component ist role, concentration, and units of concentration 
    (molar, weight per volume, volume per volume, etc...)
    Examples:
      - pH 7.5; BUFF HEPES, 50 mM; SALT NaCl, 250 mM; DET TritonX100, 1% (w/v); RED DTT, 1 mM; OTHER inhibitor, 1 mM
      - pH 8.0; BUFF Tris-Cl, 20 mM; SALT KCl, 500 mM; GLY, 5% (w/v); RED TCEP, 0.5 mM
      - pH 6.5; BUFF BTP, 100 mM; SALT NaCl, 100 mM; GLY, 10% (w/v); DET DDM, 2% (w/v); OTHER ATP, 10 mM; OTHER POPC, 5 mM

    Here is the Expert JSON schema:

    {expert_json_schema}

    Here are deposited protein-chain sequences and annotations returned by the PDBe API:

    {pdb_chain_data}

    Here is the publication in JATS format:

    {publication_jats}
"""

log = logging.getLogger(__name__)

def _successful(state: pl.DataFrame, pmcid: str, version: str) -> bool:
    return (
        state.filter(
            (pl.col("pmcid") == pmcid)
            & (pl.col("download_version") == version)
            & (pl.col("status") == "success")
        ).height
        > 0
    )

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

def build_detector_prompt(
    jats: str, pmcid: str, pdb_chain_data: list[pdb_sequences.PDBSequenceRecord]
) -> str:
    return PROMPT.format(
        publication_jats=jats, 
        expert_json_schema=EXPERT_JSON_SCHEMA,
        pmcid=pmcid,
        pdb_chain_data=json.dumps(pdb_chain_data, indent=4, ensure_ascii=False),
    )


def _resolve_pdb_chain_data(
    pdb_ids: list[str],
) -> list[pdb_sequences.PDBSequenceRecord]:
    """Resolve available PDB chain records without blocking text-only extraction."""
    try:
        return pdb_sequences.resolve_pdb_sequences(pdb_ids)
    except (requests.RequestException, ValueError) as exc:
        log.warning("Could not resolve PDBe chains: %s", exc)
        return []


async def process_publication(
    publication: dict[str, Any], agent:ollama.AsyncOllamaAgent, run_dir: Path, args: argparse.Namespace
) -> dict[str, Any]:
    download_version: str = publication["download_version"]
    pmcid = publication["pmcid"]
    target_dir = args.target_dir
    log.info(f"Extracting protocols from {download_version}")
    # publication_dir = target_dir / "publications" / download_version
    # assert publication_dir.is_dir()
    # jats_data = jats.jats_to_json(publication_dir)
    jats_file = target_dir / "publications" / download_version / f"{download_version}.xml"
    # jats_xml = jats_file.read_text()
    jats_xml = jats.compact_jats(jats_file)
    pdb_chain_data = await asyncio.to_thread(_resolve_pdb_chain_data, publication["pdb_ids"])
    prompt = build_detector_prompt(jats_xml, pmcid, pdb_chain_data)
    if args.store_prompts:
        out_path = run_dir/ f"{pmcid}_prompt.txt"
        log.info(f"Writing prompt of size {len(prompt)} to {out_path}")
        with out_path.open('w') as f:
            f.write(prompt)
    # response = ollama.ollama_json(
    #     base_url, model, prompt, publication["pmcid"], run_dir
    # )
    response = await agent.chat(prompt, ollama.SYSTEM_PROMPT, log_key=publication["pmcid"])
    if response is None:
        return None
    response = json.loads(response)
    log.info(f"Extracted protocols for {len(response['proteins'])} proteins")
    return response


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


def submit_extracted_data(s:str):
    f"""Submit the EXPER data extracted from the publication to the system, in JSON format.

    Args:
        s: the JSON string; must start with '{' and end with '}'

    """
    json.loads(s)
    return s

def wire_ollama_agent(args:argparse.Namespace, run_dir:Path) -> ollama.AsyncOllamaAgent:
    tools = agentic_tools.OLLAMA_AGENTIC_TOOLS.copy()
    tools['submit_extracted_data'] = submit_extracted_data
    ollama_agent = ollama.AsyncOllamaAgent(
        args.ollama_url, args.ollama_model,
        tools=tools, log_dir=run_dir
    )
    return ollama_agent


async def process_publications(args, publications):
    state_path = args.target_dir / EXTRACTION_STATE_FILENAME
    state = upl.load_or_create_parquet(state_path, STATE_SCHEMA)
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
    run_dir: Path = args.target_dir / "llm_runs" / run_id
    os.makedirs(run_dir, exist_ok=True)
    ollama_agent = wire_ollama_agent(args, run_dir)
    await ollama_agent.start()
    for pmcid, publication in sorted(publications.items()):
        version = str(publication["download_version"])
        if not args.force and _successful(state, pmcid, version):
            log.info("Skipping already successful %s (%s)", pmcid, version)
            continue
        try:
            log.info(f"Processing {pmcid}")
            protocols_json = await process_publication(publication, ollama_agent, run_dir, args)
            if protocols_json is None:
                continue
            out_path = run_dir/ f"{pmcid}_expert.json"
            with out_path.open('w') as f:
                json.dump(protocols_json, f, indent=4, ensure_ascii=False)
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
    await ollama_agent.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(argv)
    try:
        publications = select_publications(args.target_dir, args)
    except (OSError, ValueError, pl.exceptions.PolarsError) as exc:
        log.error("Could not select downloaded publications: %s", exc_info=exc)
        return 1
    if not publications:
        log.error("No downloaded publications matched the selection.")
        return 1
    asyncio.run(process_publications(args, publications))


if __name__ == "__main__":
    raise SystemExit(main())
