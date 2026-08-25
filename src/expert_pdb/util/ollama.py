import json
import logging
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)
SYSTEM_PROMPT = """
    You are a data processing assistant. You must respond with valid JSON only. 
"""

STATS_KEYS = ["total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration"]


def preflight_ollama(base_url: str) -> None:
    response = requests.get(base_url.rstrip("/") + "/api/tags", timeout=15)
    response.raise_for_status()


def _save_response(body: dict[str, Any], out_dir: Path | None, pmcid: str, attempt: int) -> None:
    if out_dir is None:
        return
    suffix = "" if attempt == 1 else f"_retry{attempt - 1}"
    out_path = out_dir / f"{pmcid}_ollama_full{suffix}.json"
    with out_path.open("w") as handle:
        json.dump(body, handle)


def ollama_json(
    base_url: str,
    model: str,
    prompt: str,
    pmcid: str,
    output_schema: dict[str, Any],
    out_dir: Path | None = None,
    capture_stats = False
) -> Any:
    url = base_url.rstrip("/") + "/api/generate"
    retry_instruction = (
        "\n\nYour prior response could not be parsed as JSON. Regenerate the complete response "
        "using the supplied JSON schema. Return JSON only."
    )
    for attempt in (1, 2):
        request_prompt = prompt if attempt == 1 else prompt + retry_instruction
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Prompting model %s at %s (attempt %d)", model, base_url, attempt)
        request_body: Any = {
            "model": model,
            "prompt": request_prompt,
            "stream": False,
            "system": SYSTEM_PROMPT,
            "format": output_schema,
            "think": False,
            "options": {
                "num_ctx": 81_920,
                "num_predict": 8_192,
                "temperature": 0,
            },
            "keep_alive": -1,
        }
        response = requests.post(url, json=request_body, timeout=600)
        response.raise_for_status()
        body = response.json()
        _save_response(body, out_dir, pmcid, attempt)
        if not body.get("done") or body.get("done_reason") != "stop":
            raise RuntimeError(
                "Ollama did not complete generation: "
                f"{body.get('done')}, {body.get('done_reason')}"
            )
        generated = body.get("response")
        if not isinstance(generated, str) or not generated:
            raise RuntimeError("Ollama response has no JSON response string")
        try:
            ret = json.loads(generated)
            if capture_stats:
                stats = {k:body.get(k, -1) for k in STATS_KEYS}
                return ret, stats
            else:
                return ret
        except json.JSONDecodeError as exc:
            if attempt == 2:
                raise
            log.warning("Ollama returned malformed JSON for %s; retrying once: %s", pmcid, exc)
    raise AssertionError("unreachable")
