import gzip
import io

import polars as pl

import expert_pdb.download_publications as download_publications
from expert_pdb.download_publications import STATE_FILENAME, load_or_create_state


class FakeResponse:
    def __init__(self, *, raw: bytes | None = None, payload: dict | None = None):
        self.raw = io.BytesIO(raw) if raw is not None else None
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeS3Client:
    def __init__(self):
        self.list_calls: list[dict] = []
        self.download_calls: list[tuple[str, str, object]] = []

    def list_objects_v2(self, **kwargs):
        self.list_calls.append(kwargs)
        pmcid = kwargs["Prefix"].removesuffix(".")
        return {"CommonPrefixes": [{"Prefix": f"{pmcid}.1/"}]}

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, **kwargs):
        return [{"Contents": [{"Key": f"{kwargs['Prefix']}article.xml", "Size": 7}]}]

    def download_file(self, bucket, key, destination):
        self.download_calls.append((bucket, key, destination))
        destination.write_bytes(b"article")


def _mock_download_services(monkeypatch, pmids: list[str]):
    request_calls: list[tuple[str, dict | None]] = []
    mapping = gzip.compress(
        ("pdb_id,pubmed_id\n" + "\n".join(
            f"{index}abc,{pmid}" for index, pmid in enumerate(pmids, 1)
        ) + "\n").encode()
    )

    def fake_get(url, **kwargs):
        request_calls.append((url, kwargs.get("params")))
        if url == download_publications.PDB_PUBMED_URL:
            return FakeResponse(raw=mapping)
        return FakeResponse(
            payload={
                "records": [
                    {"pmid": pmid, "pmcid": f"PMC{pmid}"} for pmid in pmids
                ]
            }
        )

    client = FakeS3Client()
    monkeypatch.setattr(download_publications.requests, "get", fake_get)
    monkeypatch.setattr(download_publications, "init_s3_client", lambda: client)
    return request_calls, client


def test_load_or_create_state_stores_unique_pmids_without_pdb_ids(tmp_path):
    mapping = pl.DataFrame(
        {
            "pdb_id": ["1abc", "2def", "3ghi"],
            "pmid": ["123", "123", "456"],
        }
    )

    state_path = tmp_path / STATE_FILENAME
    state = load_or_create_state(state_path, mapping)

    assert STATE_FILENAME == "download_state.parquet"
    assert state.columns == [
        "pmid",
        "pmcid",
        "resolution_attempted",
        "download_version",
        "downloaded",
        "download_checked",
    ]
    assert state.get_column("pmid").sort().to_list() == ["123", "456"]
    assert state.get_column("pmid").n_unique() == state.height
    assert "pdb_id" not in pl.read_parquet(state_path).columns


def test_load_or_create_state_preserves_progress_by_pmid(tmp_path):
    state_path = tmp_path / STATE_FILENAME
    pl.DataFrame(
        {
            "pmid": ["123"],
            "pmcid": ["PMC123"],
            "resolution_attempted": [True],
            "download_version": ["PMC123.42"],
            "downloaded": [True],
            "download_checked": [True],
        }
    ).write_parquet(state_path)

    state = load_or_create_state(
        state_path,
        pl.DataFrame({"pdb_id": ["1abc", "2def"], "pmid": ["123", "123"]}),
    )

    assert state.height == 1
    assert state.row(0, named=True)["pmcid"] == "PMC123"
    assert "pdb_id" not in state.columns


def test_main_resolves_pmids_only_once_when_resumed(tmp_path, monkeypatch):
    request_calls, _ = _mock_download_services(monkeypatch, ["123", "456"])
    args = [str(tmp_path), "--pdb-ids", "1abc", "2abc"]

    assert download_publications.main(args) == 0
    assert download_publications.main(args) == 0

    converter_calls = [
        params
        for url, params in request_calls
        if url != download_publications.PDB_PUBMED_URL
    ]
    assert converter_calls == [
        {
            "ids": "123,456",
            "format": "json",
            "tool": "pmc_id_resolver",
            "email": "evgeny@ebi.ac.uk",
        }
    ]


def test_main_downloads_publications_only_once_when_resumed(tmp_path, monkeypatch):
    _, client = _mock_download_services(monkeypatch, ["123", "456"])
    args = [str(tmp_path), "--pdb-ids", "1abc", "2abc"]

    assert download_publications.main(args) == 0
    assert download_publications.main(args) == 0

    assert len(client.list_calls) == 2
    assert sorted(call[1] for call in client.download_calls) == [
        "PMC123.1/article.xml",
        "PMC456.1/article.xml",
    ]
    state = pl.read_parquet(tmp_path / STATE_FILENAME).sort("pmid")
    assert state.get_column("downloaded").to_list() == [True, True]
    assert state.get_column("download_checked").to_list() == [True, True]
