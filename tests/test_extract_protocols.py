import gzip
import json

import polars as pl
import requests

import expert_pdb.extract_protocols_codex as extract_protocols_codex

JATS = """<?xml version="1.0"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
  <body><sec id="methods" sec-type="methods"><title>Methods</title>
  <p id="expression">Protein was expressed in BL21(DE3) and purified using Ni-NTA.</p>
  </sec></body>
  <supplementary-material xlink:href="supplement.pdf">
    <label>Supplementary methods</label>
  </supplementary-material>
  <ref-list><ref id="ref1"><label>42</label>
    <mixed-citation>Smith et al. Science 2024. PMID: 1234. doi:10.1000/example</mixed-citation>
  </ref></ref-list>
</article>
"""


class FakeResponse:
    def __init__(self, payload: dict | None = None):
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def _prepare_download(target_dir, pmcid="PMC100", pdb_ids=None):
    pdb_ids = pdb_ids or ["1abc"]
    csv = "pdb_id,pubmed_id\n" + "\n".join(f"{pdb_id},100" for pdb_id in pdb_ids) + "\n"
    (target_dir / "pdb_pubmed.csv.gz").write_bytes(gzip.compress(csv.encode()))
    pl.DataFrame(
        {
            "pmid": ["100"],
            "pmcid": [pmcid],
            "resolution_attempted": [True],
            "download_version": [f"{pmcid}.1"],
            "downloaded": [True],
            "download_checked": [True],
        }
    ).write_parquet(target_dir / "download_state.parquet")
    package = target_dir / "publications" / f"{pmcid}.1"
    package.mkdir(parents=True)
    (package / "article.xml").write_text(JATS)
    (package / "supplement.pdf").write_bytes(b"not parsed")


def _model_response(status="retrieved"):
    return {
        "protocol_status": status,
        "protocol_chunks": (
            [{"locator": "article.xml#expression", "text": "Protein was expressed in BL21(DE3)."}]
            if status == "retrieved"
            else []
        ),
        "constructs": [
            {
                "construct_id": "construct-a",
                "host": "e-coli",
                "pdb_ids": [],
                "fields": {
                    "T1": {
                        "value": "Example protein",
                        "confidence": 0.9,
                        "evidence_locators": ["article.xml#expression"],
                    },
                    "T4": {
                        "value": "P12345",
                        "confidence": 0.8,
                        "evidence_locators": ["article.xml#expression"],
                    },
                    "E3": {
                        "value": {"value": 2, "unit": "L"},
                        "confidence": 0.8,
                        "evidence_locators": ["article.xml#expression"],
                    },
                    "E11": {
                        "value": "ph 7.5; buff HEPES, 50 mM; salt NaCl, 250 mM",
                        "confidence": 0.8,
                        "evidence_locators": ["article.xml#expression"],
                    },
                    "P4": {
                        "value": "yes",
                        "confidence": 0.8,
                        "evidence_locators": ["article.xml#expression"],
                    },
                    "Q1": {
                        "value": "95%",
                        "confidence": 0.6,
                        "evidence_locators": ["article.xml#expression"],
                    },
                    "EXTRA": {"value": "kept as surplus"},
                },
                "surplus_facts": [
                    {
                        "name": "detergent incubation",
                        "value": "30 minutes",
                        "confidence": 0.7,
                        "evidence_locators": ["article.xml#expression"],
                    }
                ],
                "protein_identifiers": {
                    "uniprot_ids": ["P12345"],
                    "genbank_ids": ["ABC123"],
                    "gene_names": ["EXAMPLE"],
                    "organisms": ["Escherichia coli"],
                    "other_identifiers": ["target-1"],
                },
                "n_terminal_tags": ["His6"],
                "c_terminal_tags": [],
            }
        ],
        "supplementary_leads": [],
        "citation_leads": [],
    }


def _mock_ollama(monkeypatch, response):
    calls = {"post": 0}

    def fake_get(url, **kwargs):
        assert url == "http://ollama.test/api/tags"
        return FakeResponse({"models": []})

    def fake_post(url, **kwargs):
        assert url == "http://ollama.test/api/generate"
        calls["post"] += 1
        return FakeResponse({"response": json.dumps(response)})

    monkeypatch.setattr(extract_protocols_codex.requests, "get", fake_get)
    monkeypatch.setattr(extract_protocols_codex.requests, "post", fake_post)
    return calls


def test_main_writes_typed_records_evidence_and_run_json(tmp_path, monkeypatch):
    _prepare_download(tmp_path, pdb_ids=["1abc", "2def"])
    calls = _mock_ollama(monkeypatch, _model_response())

    assert extract_protocols_codex.main([str(tmp_path), "--ollama-url", "http://ollama.test"]) == 0
    assert calls["post"] == 1

    records = pl.read_parquet(tmp_path / "expert_records_e-coli.parquet").sort("pdb_id")
    assert records.get_column("pdb_id").to_list() == ["1abc", "2def"]
    assert records.get_column("pdb_linkage").to_list() == ["publication_inferred"] * 2
    assert records.get_column("T4").to_list() == ["P12345", "P12345"]
    assert "uniprot_id" not in records.columns
    assert records.get_column("E3").to_list() == [{"value": 2.0, "unit": "L"}] * 2
    assert (
        records.get_column("E11").to_list() == ["pH 7.5; BUFF HEPES, 50 mM; SALT NaCl, 250 mM"] * 2
    )
    assert records.get_column("P4").to_list() == [True, True]
    assert records.get_column("Q1").to_list() == [95.0, 95.0]
    assert records.get_column("surplus_facts").to_list()[0][1]["name"] == "EXTRA"

    protocols = pl.read_parquet(tmp_path / "protein_production_protocols.parquet")
    assert protocols.get_column("status").to_list() == ["retrieved", "retrieved"]
    assert "article.xml#expression" in protocols.get_column("evidence_locators").to_list()[0]
    constructs = pl.read_parquet(tmp_path / "construct_data.parquet")
    assert constructs.get_column("n_terminal_tags").to_list() == [["His6"], ["His6"]]
    state = pl.read_parquet(tmp_path / "extraction_state.parquet")
    assert state.get_column("status").to_list() == ["success"]
    run_json = next((tmp_path / "llm_runs").rglob("PMC100.json"))
    assert json.loads(run_json.read_text())["metadata"]["schema_version"] == "expert-2026-05-26"


def test_main_resumes_and_force_replaces_publication_rows(tmp_path, monkeypatch):
    _prepare_download(tmp_path)
    calls = _mock_ollama(monkeypatch, _model_response())
    arguments = [str(tmp_path), "--ollama-url", "http://ollama.test"]

    assert extract_protocols_codex.main(arguments) == 0
    assert extract_protocols_codex.main(arguments) == 0
    assert calls["post"] == 1
    assert extract_protocols_codex.main([*arguments, "--force"]) == 0
    assert calls["post"] == 2
    assert pl.read_parquet(tmp_path / "expert_records_e-coli.parquet").height == 1


def test_main_records_bad_model_json_and_continues(tmp_path, monkeypatch):
    _prepare_download(tmp_path)
    calls = _mock_ollama(monkeypatch, {"protocol_status": "retrieved"})

    assert extract_protocols_codex.main([str(tmp_path), "--ollama-url", "http://ollama.test"]) == 1
    assert calls["post"] == 1
    state = pl.read_parquet(tmp_path / "extraction_state.parquet")
    assert state.get_column("status").to_list() == ["failed"]
    assert not (tmp_path / "protein_production_protocols.parquet").exists()


def test_main_aborts_before_processing_when_ollama_is_unavailable(tmp_path, monkeypatch):
    _prepare_download(tmp_path)

    def unavailable(url, **kwargs):
        raise requests.ConnectionError("not running")

    monkeypatch.setattr(extract_protocols_codex.requests, "get", unavailable)
    assert extract_protocols_codex.main([str(tmp_path), "--ollama-url", "http://ollama.test"]) == 1
    assert not (tmp_path / "extraction_state.parquet").exists()


def test_parse_jats_identifies_supplement_and_reference_identifiers(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "article.xml").write_text(JATS)
    (package / "supplement.pdf").write_bytes(b"not parsed")

    parsed = extract_protocols_codex.parse_jats(package)
    assert parsed["supplements"] == [
        {
            "label": "Supplementary methods",
            "href": "supplement.pdf",
            "guessed_file": "supplement.pdf",
        }
    ]
    assert parsed["references"][0]["identifiers"]["doi"] == ["10.1000/example"]
    assert parsed["references"][0]["identifiers"]["pmid"] == ["1234"]


def test_deferred_source_info_preserves_supplement_paths_and_reference_ids(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "article.xml").write_text(JATS)
    (package / "supplement.pdf").write_bytes(b"not parsed")
    source = extract_protocols_codex.parse_jats(package)

    supplement = {
        "protocol_status": "supplement",
        "supplementary_leads": [{"description": "See supplementary methods", "identifiers": {}}],
        "citation_leads": [],
    }
    citation = {
        "protocol_status": "citation",
        "supplementary_leads": [],
        "citation_leads": [{"description": "Reference 42", "identifiers": {}}],
    }
    assert "supplement.pdf" in extract_protocols_codex._deferred_info(supplement, source)
    reference_info = extract_protocols_codex._deferred_info(citation, source)
    assert "pmid=1234" in reference_info
    assert "doi=10.1000/example" in reference_info


def test_static_schema_covers_every_expression_template():
    expected_fields = {
        "e-coli": {"EB1", "EB2", "EB3"},
        "insect": {"EI1", "EI2", "EI3", "EI4"},
        "mammalian": {"EM1", "EM2", "EM3", "EM4", "EM5"},
        "cell-free": {"CFC1", "CFL4", "CFE11", "CFE15"},
    }
    for host, identifiers in expected_fields.items():
        schema = extract_protocols_codex._expert_schema(host)
        assert identifiers.issubset(schema)
        assert "T1" in schema
        assert "protein_name" not in schema
        assert "T1_confidence" in schema
