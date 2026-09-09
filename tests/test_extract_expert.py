from types import SimpleNamespace

import requests

from expert_pdb import extract_expert
from expert_pdb.extract_expert import PROMPT, _resolve_pdb_chain_data, build_detector_prompt


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


def test_extraction_prompt_does_not_advertise_ncbi_mcp_tools():
    assert "mcp_ncbi" not in PROMPT


def test_wire_ollama_agent_uses_only_local_agentic_tools(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_agent(base_url, model, **kwargs):
        captured.update({"base_url": base_url, "model": model, **kwargs})
        return object()

    monkeypatch.setattr(extract_expert.ollama, "AsyncOllamaAgent", fake_agent)
    args = SimpleNamespace(ollama_url="http://ollama.test", ollama_model="test-model")

    extract_expert.wire_ollama_agent(args, tmp_path)

    assert set(captured) == {"base_url", "model", "extra_tools", "log_dir"}
    assert set(captured["extra_tools"]) == {
        "python",
        "get_cds_for_protein_accession",
        "submit_extracted_data",
    }
