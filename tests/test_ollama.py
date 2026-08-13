import json

import pytest

from expert_pdb.util import ollama


class FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self.payload


def test_ollama_json_uses_schema_disables_thinking_and_bounds_output(monkeypatch, tmp_path):
    calls: list[dict[str, object]] = []

    def fake_post(url, **kwargs):
        assert url == "http://ollama.test/api/generate"
        calls.append(kwargs["json"])
        return FakeResponse({"done": True, "done_reason": "stop", "response": "[]"})

    monkeypatch.setattr(ollama.requests, "post", fake_post)
    schema = {"type": "array", "items": {"type": "object"}}

    result = ollama.ollama_json("http://ollama.test", "model", "prompt", "PMC1", schema, tmp_path)
    assert result == []

    assert calls[0]["format"] == schema
    assert calls[0]["think"] is False
    assert calls[0]["options"] == {"num_ctx": 81920, "num_predict": 8192, "temperature": 0}
    assert json.loads((tmp_path / "PMC1_ollama_full.json").read_text())["response"] == "[]"


def test_ollama_json_retries_once_after_malformed_json(monkeypatch, tmp_path):
    calls: list[dict[str, object]] = []
    responses = iter(
        [
            FakeResponse({"done": True, "done_reason": "stop", "response": "{not json"}),
            FakeResponse({"done": True, "done_reason": "stop", "response": "[]"}),
        ]
    )

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        return next(responses)

    monkeypatch.setattr(ollama.requests, "post", fake_post)

    assert ollama.ollama_json("http://ollama.test", "model", "prompt", "PMC1", {}, tmp_path) == []

    assert len(calls) == 2
    assert "prior response could not be parsed" in calls[1]["prompt"]
    assert (tmp_path / "PMC1_ollama_full.json").exists()
    assert (tmp_path / "PMC1_ollama_full_retry1.json").exists()


def test_ollama_json_raises_after_second_malformed_response(monkeypatch):
    def fake_post(url, **kwargs):
        return FakeResponse({"done": True, "done_reason": "stop", "response": "{not json"})

    monkeypatch.setattr(ollama.requests, "post", fake_post)

    with pytest.raises(json.JSONDecodeError):
        ollama.ollama_json("http://ollama.test", "model", "prompt", "PMC1", {})
