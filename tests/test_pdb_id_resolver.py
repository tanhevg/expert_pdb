import json

import pytest

from expert_pdb.util import pdb_id_resolver


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.payload


def test_resolve_pdb_id_returns_identifiers_for_each_mapped_chain(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, *, timeout: float) -> FakeResponse:
        calls.append(url)
        assert timeout == 12
        if "pdbe" in url:
            return FakeResponse(
                {
                    "1abc": {
                        "UniProt": {
                            "P11111": {
                                "mappings": [
                                    {"chain_id": "A"},
                                    {"chain_id": "B"},
                                ]
                            },
                            "Q22222": {"mappings": [{"chain_id": "A"}]},
                        }
                    }
                }
            )
        if url.endswith("P11111.json"):
            return FakeResponse(
                {
                    "uniProtKBCrossReferences": [
                        {"database": "HGNC", "id": "HGNC:1"},
                        {"database": "PDB", "id": "1ABC"},
                    ]
                }
            )
        assert url.endswith("Q22222.json")
        return FakeResponse(
            {
                "uniProtKBCrossReferences": [
                    {"database": "HGNC", "id": "HGNC:2"},
                    {"database": "HGNC", "id": "HGNC:1"},
                ]
            }
        )

    monkeypatch.setattr(pdb_id_resolver.requests, "get", fake_get)

    identifiers = pdb_id_resolver.resolve_pdb_id("1ABC", timeout=12)

    assert identifiers == {
        "A": {"uniprot_id": "P11111", "hgnc_id": "HGNC:1"},
        "B": {"uniprot_id": "P11111", "hgnc_id": "HGNC:1"},
    }
    assert json.loads(json.dumps(identifiers)) == identifiers
    assert calls.count(pdb_id_resolver.UNIPROT_RECORD_URL.format(accession="P11111")) == 1


def test_resolve_pdb_id_rejects_invalid_pdb_id():
    with pytest.raises(ValueError, match="Invalid PDB ID"):
        pdb_id_resolver.resolve_pdb_id("too-long")
