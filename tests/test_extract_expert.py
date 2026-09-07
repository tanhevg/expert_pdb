import requests

from expert_pdb.extract_expert import _resolve_pdb_chain_data, build_detector_prompt


def test_build_detector_prompt_includes_pdbe_sequences_for_constructs():
    prompt = build_detector_prompt(
        "<article />",
        "PMC123",
        [
            {
                "sequence": "MHHHHHAA",
                "pdb_chains": [{"pdb_id": "1abc", "entity_id": 1, "chain_id": "A"}],
                "uniprot_mappings": [],
                "gene_names": ["GENE1"],
            }
        ],
    )

    assert "populate C2 with" in prompt
    assert "PDBe UniProt mappings take precedence" in prompt
    assert '"sequence": "MHHHHHAA"' in prompt
    assert "<article />" in prompt
    assert prompt.index('"sequence": "MHHHHHAA"') < prompt.index("<article />")


def test_resolve_pdb_chain_data_returns_empty_list_when_pdbe_fails(monkeypatch):
    def fake_resolve(pdb_ids: list[str]) -> list[dict]:
        raise requests.RequestException("PDBe unavailable")

    monkeypatch.setattr(
        "expert_pdb.extract_expert.pdb_sequences.resolve_pdb_sequences", fake_resolve
    )

    assert _resolve_pdb_chain_data(["1abc", "2def"]) == []
