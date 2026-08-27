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
    ollama,
    polars as upl,
    util,
    jats,
    pdb_id_resolver
)

from expert_pdb.download_publications import STATE_FILENAME, configure_logging, read_mapping
from expert_pdb.extract_protocols import select_publications, parse_args, _successful, EXTRACTION_STATE_FILENAME, STATE_SCHEMA
from expert_pdb import expert_schema

# EXPERT_JSON_SCHEMA = json.dumps(expert_schema.expert_json_schema(), indent=4, ensure_ascii=False)

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
    Read the publication and extract the information about protein production from it in Expert format, as defined below. 
    The response should be a valid JSON document. Here is the Expert JSON schema:

    {expert_json_schema}

    Populate as many fields as possible.
    Do not populate the construct sequences if they are not available in the publication text.

    If the publication contains production protocols for multiple proteins or construct definitions, 
    the JSON array should contain multiple elements. Be as specific as possible, do not try to 
    represent multiple constructs with the same JSON object. Having multiple JSON objects with 
    duplicated fields is fine. Each construct definition encountered in the text should be 
    represented with an entry in `proteins` array.

    If the publication identifies the target proteins in ways that are not supported by Expert, i.e. not
    HGNC gene names or Uniprot or PDB ids, these additional target ids should be included in the JSON
    as additional fields. These fields should be marked with prefix 'TN_', and the id system, if 
    available. For example, {{... "TN_NCBI_Gene_ID": "1105", "TN_ENSEML_ID": "ENSG00000153922.14" }}.
    Populate HGNC, Uniprot and PDB ids only if they are present in the publication text; do not try to hallucinate them.

    If the publication descibes a protein complex, populate the 'CX...' fields.

    Populate the PMC id of the publication `PMCID={pmcid}` in the 'O1' field.

    Do not include the completeness. 

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

    Here is the publication in JATS format:

    {publication_jats}
"""


log = logging.getLogger(__name__)


def build_detector_prompt(jats: str, pmcid:str) -> str:
    # pdb_ids = {pdb_id: pdb_id_resolver.resolve_pdb_id(pdb_id) for pdb_id in pdb_ids}
    # pdb_ids = json.dumps(pdb_ids, indent=4)
    return PROMPT.format(
        # pdb_ids=pdb_ids, 
        publication_jats=jats, 
        expert_json_schema=EXPERT_JSON_SCHEMA,
        pmcid=pmcid
    )


def process_publication(publication: dict[str, Any], run_dir:Path, args:argparse.Namespace):
    download_version:str = publication["download_version"]
    pmcid = publication["pmcid"]
    target_dir = args.target_dir
    base_url = args.ollama_url
    model = args.ollama_model
    log.info(f"Extracting protocols from {download_version}")
    # publication_dir = target_dir / "publications" / download_version
    # assert publication_dir.is_dir()
    # jats_data = jats.jats_to_json(publication_dir)
    jats_file = target_dir / "publications" / download_version / f"{download_version}.xml"
    # jats_xml = jats_file.read_text()
    jats_xml = jats.compact_jats(jats_file)
    prompt = build_detector_prompt(jats_xml, pmcid)
    # prompt = build_detector_prompt(jats_xml, publication['pdb_ids'])
    if args.store_prompts:
        out_path = run_dir/ f"{pmcid}_prompt.txt"
        log.info(f"Writing prompt of size {len(prompt)} to {out_path}")
        with out_path.open('w') as f:
            f.write(prompt)
    response = ollama.ollama_json(
        base_url, model, prompt, publication["pmcid"], run_dir
    )
    log.info(f"Extracted protocols for {len(response['proteins'])} proteins")
    return response



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
    for pmcid, publication in sorted(publications.items()):
        version = str(publication["download_version"])
        if not args.force and _successful(state, pmcid, version):
            log.info("Skipping already successful %s (%s)", pmcid, version)
            continue
        try:
            log.info(f"Processing {pmcid}")
            protocols_json = process_publication(publication, run_dir, args)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
