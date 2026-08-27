"""Resolve PDB chains to UniProt accessions and HGNC identifiers."""

import re
from collections.abc import Mapping
from typing import Any, TypedDict

import requests

PDBE_UNIPROT_MAPPING_URL = "https://www.ebi.ac.uk/pdbe/api/mappings/uniprot/{pdb_id}"
UNIPROT_RECORD_URL = "https://rest.uniprot.org/uniprotkb/{accession}.json"
DEFAULT_TIMEOUT_SECONDS = 30

_PDB_ID_PATTERN = re.compile(r"^[0-9][A-Za-z0-9]{3}$")


class ChainIdentifiers(TypedDict):
    """External identifiers associated with a PDB author chain."""

    uniprot_id: str
    hgnc_id: str | None


def resolve_pdb_id(
    pdb_id: str, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> dict[str, ChainIdentifiers]:
    """Return UniProt and HGNC identifiers for every mapped chain in a PDB entry.

    The returned dictionary is keyed by author chain ID. Each value is a plain
    dictionary and can therefore be passed directly to :func:`json.dumps`.
    When a chain has multiple mappings, the lexicographically first UniProt and
    HGNC identifiers are selected as primary identifiers. Chains without a
    UniProt mapping are absent because neither source provides a reliable gene
    mapping for them. HGNC identifiers have the form ``HGNC:1234``.

    Args:
        pdb_id: Four-character PDB identifier.
        timeout: Per-request timeout in seconds.

    Raises:
        ValueError: If ``pdb_id`` is not a four-character PDB identifier.
        requests.HTTPError: If PDBe or UniProt cannot serve a requested record.
    """
    normalized_pdb_id = _normalize_pdb_id(pdb_id)
    mapping_response = requests.get(
        PDBE_UNIPROT_MAPPING_URL.format(pdb_id=normalized_pdb_id), timeout=timeout
    )
    mapping_response.raise_for_status()

    chain_uniprot_ids = _chain_uniprot_ids(mapping_response.json(), normalized_pdb_id)
    uniprot_ids = set().union(*chain_uniprot_ids.values()) if chain_uniprot_ids else set()
    hgnc_ids_by_uniprot_id = {
        accession: _hgnc_ids_for_uniprot(accession, timeout=timeout)
        for accession in uniprot_ids
    }

    return {
        chain_id: ChainIdentifiers(
            uniprot_id=min(accessions),
            hgnc_id=next(
                iter(
                    sorted(
                        {
                            hgnc_id
                            for accession in accessions
                            for hgnc_id in hgnc_ids_by_uniprot_id[accession]
                        }
                    )
                ),
                None,
            ),
        )
        for chain_id, accessions in sorted(chain_uniprot_ids.items())
    }


def _normalize_pdb_id(pdb_id: str) -> str:
    normalized_pdb_id = pdb_id.strip().lower()
    if not _PDB_ID_PATTERN.fullmatch(normalized_pdb_id):
        raise ValueError(f"Invalid PDB ID: {pdb_id!r}")
    return normalized_pdb_id


def _chain_uniprot_ids(payload: Mapping[str, Any], pdb_id: str) -> dict[str, set[str]]:
    entry = payload.get(pdb_id, {})
    uniprot_mappings = entry.get("UniProt", {}) if isinstance(entry, Mapping) else {}
    chain_uniprot_ids: dict[str, set[str]] = {}

    if not isinstance(uniprot_mappings, Mapping):
        return chain_uniprot_ids

    for accession, mapping_data in uniprot_mappings.items():
        if not isinstance(accession, str) or not isinstance(mapping_data, Mapping):
            continue
        mappings = mapping_data.get("mappings", [])
        if not isinstance(mappings, list):
            continue
        for mapping in mappings:
            if not isinstance(mapping, Mapping):
                continue
            chain_id = mapping.get("chain_id")
            if isinstance(chain_id, str) and chain_id:
                chain_uniprot_ids.setdefault(chain_id, set()).add(accession)

    return chain_uniprot_ids


def _hgnc_ids_for_uniprot(accession: str, *, timeout: float) -> set[str]:
    response = requests.get(UNIPROT_RECORD_URL.format(accession=accession), timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    cross_references = payload.get("uniProtKBCrossReferences", [])
    if not isinstance(cross_references, list):
        return set()

    return {
        identifier
        for cross_reference in cross_references
        if isinstance(cross_reference, Mapping)
        and cross_reference.get("database") == "HGNC"
        and isinstance(identifier := cross_reference.get("id"), str)
        and identifier
    }


if __name__ == '__main__':
    import json
    identifiers = resolve_pdb_id("8ent")
    print(json.dumps(identifiers, indent=4, ensure_ascii=False))
