"""Codex-generated. Resolve deposited protein-chain sequences and annotations from PDBe."""

import argparse
import json
import logging
import re
from collections.abc import Mapping
from typing import Any, TypedDict

import requests

PDBE_ENTRY_MOLECULES_URL = "https://www.ebi.ac.uk/pdbe/api/v2/pdb/entry/molecules/{pdb_id}"
PDBE_UNIPROT_MAPPING_URL = "https://www.ebi.ac.uk/pdbe/api/v2/mappings/uniprot/{pdb_id}"
DEFAULT_TIMEOUT_SECONDS = 30

_PDB_ID_PATTERN = re.compile(r"^[0-9][A-Za-z0-9]{3}$")

log = logging.getLogger(__name__)


class PDBChainReference(TypedDict):
    """A PDB entity and author chain representing a deposited sequence."""

    pdb_id: str
    chain_id: str
    entity_id: int


class PDBChainSequence(TypedDict):
    """Deposited protein-chain data used while collecting sequence records."""

    pdb_id: str
    chain_id: str
    entity_id: int
    sequence: str
    uniprot_mappings: list["UniProtMapping"]
    gene_names: list[str]


class UniProtMapping(TypedDict):
    """The UniProt residue range represented by a PDB chain segment."""

    uniprot_id: str
    uniprot_start: int | None
    uniprot_end: int | None
    pdb_start: int | None
    pdb_end: int | None
    coverage: float | None


class PDBSequenceRecord(TypedDict):
    """One unique deposited sequence and every PDB chain representing it."""

    sequence: str
    pdb_chains: list[PDBChainReference]
    uniprot_mappings: list[UniProtMapping]
    gene_names: list[str]


def resolve_pdb_sequences(
    pdb_ids: list[str], *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> list[PDBSequenceRecord]:
    """Return unique deposited sequences across the requested PDB entries.

    Each result includes every PDB entity and author chain that contains the
    sequence in ``pdb_chains``. UniProt mappings and gene names are merged from
    all of those chains. The deposited polymer sequence can include engineered
    mutations and expression tags present in the submitted construct.

    Args:
        pdb_ids: Four-character PDB identifiers.
        timeout: Per-request timeout in seconds.

    Raises:
        ValueError: If any PDB ID is not a four-character PDB identifier.
        requests.HTTPError: If PDBe cannot serve either requested record.
    """
    normalized_pdb_ids = list(dict.fromkeys(_normalize_pdb_id(pdb_id) for pdb_id in pdb_ids))
    chains: list[PDBChainSequence] = []
    for pdb_id in normalized_pdb_ids:
        chains.extend(_resolve_pdb_chain_sequences(pdb_id, timeout=timeout).values())
    return _deduplicate_sequences(chains)


def _resolve_pdb_chain_sequences(
    pdb_id: str, *, timeout: float
) -> dict[str, PDBChainSequence]:
    molecules_response = requests.get(
        PDBE_ENTRY_MOLECULES_URL.format(pdb_id=pdb_id), timeout=timeout
    )
    molecules_response.raise_for_status()
    mappings_response = requests.get(
        PDBE_UNIPROT_MAPPING_URL.format(pdb_id=pdb_id), timeout=timeout
    )
    mappings_response.raise_for_status()

    uniprot_mappings_by_chain = _uniprot_mappings_by_chain(
        mappings_response.json(), pdb_id
    )
    return _protein_chains(
        molecules_response.json(), pdb_id, uniprot_mappings_by_chain
    )


def _deduplicate_sequences(chains: list[PDBChainSequence]) -> list[PDBSequenceRecord]:
    records: dict[str, PDBSequenceRecord] = {}
    for chain in chains:
        record = records.setdefault(
            chain["sequence"],
            PDBSequenceRecord(
                sequence=chain["sequence"],
                pdb_chains=[],
                uniprot_mappings=[],
                gene_names=[],
            ),
        )
        record["pdb_chains"].append(
            PDBChainReference(
                pdb_id=chain["pdb_id"],
                entity_id=chain["entity_id"],
                chain_id=chain["chain_id"],
            )
        )
        record["uniprot_mappings"].extend(chain["uniprot_mappings"])
        record["gene_names"].extend(chain["gene_names"])

    for record in records.values():
        record["pdb_chains"] = sorted(
            {tuple(reference.items()): reference for reference in record["pdb_chains"]}.values(),
            key=lambda reference: (reference["pdb_id"], reference["entity_id"], reference["chain_id"]),
        )
        record["uniprot_mappings"] = _unique_mappings(record["uniprot_mappings"])
        record["gene_names"] = sorted(set(record["gene_names"]))
    return [records[sequence] for sequence in sorted(records)]


def _unique_mappings(mappings: list[UniProtMapping]) -> list[UniProtMapping]:
    unique = {tuple(mapping.items()): mapping for mapping in mappings}
    return sorted(
        unique.values(),
        key=lambda mapping: (
            mapping["uniprot_id"],
            mapping["uniprot_start"] is None,
            mapping["uniprot_start"] or 0,
            mapping["uniprot_end"] is None,
            mapping["uniprot_end"] or 0,
        ),
    )


def _normalize_pdb_id(pdb_id: str) -> str:
    normalized_pdb_id = pdb_id.strip().lower()
    if not _PDB_ID_PATTERN.fullmatch(normalized_pdb_id):
        raise ValueError(f"Invalid PDB ID: {pdb_id!r}")
    return normalized_pdb_id


def _protein_chains(
    payload: Mapping[str, Any],
    pdb_id: str,
    uniprot_mappings_by_chain: Mapping[str, list[UniProtMapping]],
) -> dict[str, PDBChainSequence]:
    molecules = payload.get(pdb_id, [])
    if not isinstance(molecules, list):
        return {}

    chains: dict[str, PDBChainSequence] = {}
    for molecule in molecules:
        if not isinstance(molecule, Mapping):
            continue
        molecule_type = molecule.get("molecule_type")
        sequence = molecule.get("sequence")
        entity_id = molecule.get("entity_id")
        if (
            not isinstance(molecule_type, str)
            or not molecule_type.lower().startswith("polypeptide")
            or not isinstance(sequence, str)
            or not sequence
            or not isinstance(entity_id, int)
        ):
            continue
        gene_names = _strings(molecule.get("gene_name"))
        for chain_id in _strings(molecule.get("in_chains")):
            uniprot_mappings = uniprot_mappings_by_chain.get(chain_id, [])
            chains[chain_id] = PDBChainSequence(
                pdb_id=pdb_id,
                chain_id=chain_id,
                entity_id=entity_id,
                sequence=sequence,
                uniprot_mappings=uniprot_mappings,
                gene_names=gene_names,
            )
    return dict(sorted(chains.items()))


def _uniprot_mappings_by_chain(
    payload: Mapping[str, Any], pdb_id: str
) -> dict[str, list[UniProtMapping]]:
    entry = payload.get(pdb_id, {})
    uniprot_mappings = entry.get("UniProt", {}) if isinstance(entry, Mapping) else {}
    if not isinstance(uniprot_mappings, Mapping):
        return {}

    chain_uniprot_mappings: dict[str, list[UniProtMapping]] = {}
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
                chain_uniprot_mappings.setdefault(chain_id, []).append(
                    UniProtMapping(
                        uniprot_id=accession,
                        uniprot_start=_integer(mapping.get("unp_start")),
                        uniprot_end=_integer(mapping.get("unp_end")),
                        pdb_start=_residue_number(mapping.get("start")),
                        pdb_end=_residue_number(mapping.get("end")),
                        coverage=_number(mapping.get("coverage")),
                    )
                )
    return {
        chain_id: sorted(
            mappings,
            key=lambda mapping: (
                mapping["uniprot_id"],
                mapping["uniprot_start"] is None,
                mapping["uniprot_start"] or 0,
                mapping["uniprot_end"] is None,
                mapping["uniprot_end"] or 0,
            ),
        )
        for chain_id, mappings in chain_uniprot_mappings.items()
    }


def _residue_number(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    return _integer(value.get("residue_number"))


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


def main(argv: list[str] | None = None) -> int:
    """Print PDBe protein-chain sequences for one or more PDB entries as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdb_ids", nargs="*", metavar="PDB_ID")
    args = parser.parse_args(argv)
    pdb_ids = args.pdb_ids
    ret = 0
    if not pdb_ids:
        pdb_ids = [['9t9e', '9t9f', '9t9g', '9t9h', '9t9i'], ['8g1r']]

    for pdb_id in pdb_ids:
        try:
            records = resolve_pdb_sequences(pdb_id)
        except (ValueError, requests.RequestException) as exc:
            log.error("Could not resolve PDB sequences: %s", exc)
            ret = 1

        print(json.dumps(records, indent=2, ensure_ascii=False))
    return ret


if __name__ == "__main__":
    raise SystemExit(main())
