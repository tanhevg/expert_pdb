import json

import pytest
import requests

from expert_pdb.util import pdb_sequences


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.payload


def test_resolve_pdb_sequences_deduplicates_protein_chains_and_merges_annotations(monkeypatch):
    def fake_get(url: str, *, timeout: float) -> FakeResponse:
        assert timeout == 12
        if "entry/molecules" in url:
            return FakeResponse(
                {
                    "1abc": [
                        {
                            "molecule_type": "polypeptide(L)",
                            "entity_id": 1,
                            "in_chains": ["B", "A"],
                            "sequence": "MHHHHHAA",
                            "gene_name": ["GENE2", "GENE1", "GENE1"],
                        },
                        {
                            "molecule_type": "bound",
                            "entity_id": 2,
                            "in_chains": ["C"],
                        },
                    ]
                }
            )
        assert "mappings/uniprot" in url
        return FakeResponse(
            {
                "1abc": {
                    "UniProt": {
                        "P11111": {"mappings": [{"chain_id": "A"}]},
                        "Q22222": {
                            "mappings": [
                                {
                                    "chain_id": "A",
                                    "unp_start": 270,
                                    "unp_end": 443,
                                    "start": {"residue_number": 1},
                                    "end": {"residue_number": 174},
                                    "coverage": 0.102,
                                },
                                {"chain_id": "B"},
                            ]
                        },
                    }
                }
            }
        )

    monkeypatch.setattr(pdb_sequences.requests, "get", fake_get)

    sequences = pdb_sequences.resolve_pdb_sequences(["1ABC"], timeout=12)

    assert sequences == [
        {
            "sequence": "MHHHHHAA",
            "pdb_chains": [
                {"pdb_id": "1abc", "entity_id": 1, "chain_id": "A"},
                {"pdb_id": "1abc", "entity_id": 1, "chain_id": "B"},
            ],
            "uniprot_mappings": [
                {
                    "uniprot_id": "P11111",
                    "uniprot_start": None,
                    "uniprot_end": None,
                    "pdb_start": None,
                    "pdb_end": None,
                    "coverage": None,
                },
                {
                    "uniprot_id": "Q22222",
                    "uniprot_start": 270,
                    "uniprot_end": 443,
                    "pdb_start": 1,
                    "pdb_end": 174,
                    "coverage": 0.102,
                },
                {
                    "uniprot_id": "Q22222",
                    "uniprot_start": None,
                    "uniprot_end": None,
                    "pdb_start": None,
                    "pdb_end": None,
                    "coverage": None,
                },
            ],
            "gene_names": ["GENE1", "GENE2"],
        }
    ]
    assert json.loads(json.dumps(sequences)) == sequences


def test_resolve_pdb_sequences_rejects_invalid_pdb_id():
    with pytest.raises(ValueError, match="Invalid PDB ID"):
        pdb_sequences.resolve_pdb_sequences(["too-long"])


def test_deduplicate_sequences_merges_references_from_multiple_pdb_entries():
    records = pdb_sequences._deduplicate_sequences(
        [
            {
                "pdb_id": "1abc",
                "entity_id": 1,
                "chain_id": "A",
                "sequence": "MA",
                "uniprot_mappings": [],
                "gene_names": ["GENE1"],
            },
            {
                "pdb_id": "2def",
                "entity_id": 3,
                "chain_id": "Z",
                "sequence": "MA",
                "uniprot_mappings": [],
                "gene_names": ["GENE2"],
            },
        ]
    )

    assert records == [
        {
            "sequence": "MA",
            "pdb_chains": [
                {"pdb_id": "1abc", "entity_id": 1, "chain_id": "A"},
                {"pdb_id": "2def", "entity_id": 3, "chain_id": "Z"},
            ],
            "uniprot_mappings": [],
            "gene_names": ["GENE1", "GENE2"],
        }
    ]


