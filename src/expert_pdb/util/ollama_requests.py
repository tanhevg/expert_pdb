import json
import logging
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)
# SYSTEM_PROMPT = """
#     You are a data processing assistant. You must respond with valid JSON only. 
# """
SYSTEM_PROMPT = """
    You are a data processing assistant. You are allowed to think before generating the response.
    The final response must be a valid JSON. 
"""

STATS_KEYS = ["total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration"]


def preflight_ollama(base_url: str) -> None:
    response = requests.get(base_url.rstrip("/") + "/api/tags", timeout=15)
    response.raise_for_status()


def _save_response(body: str, out_dir: Path | None, pmcid: str,) -> None:
    if out_dir is None:
        return
    out_path = out_dir / f"{pmcid}_ollama_full.json"
    with out_path.open("w") as handle:
        handle.write(body)


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
    request_prompt = prompt
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Prompting model %s at %s", model, base_url)
    request_body: Any = {
        "model": model,
        "prompt": request_prompt,
        # "stream": False,
        # "system": SYSTEM_PROMPT,
        # "format": output_schema,
        # "think": False,
        # "options": {
        #     "num_ctx": 81_920,
        #     "num_predict": 8_192,
        #     "temperature": 0,
        # },
        "keep_alive": -1,
    }
    response = requests.post(url, json=request_body, timeout=600)
    response.raise_for_status()
    log.debug(response.text)
    _save_response(response.text, out_dir, pmcid)
    body = response.json()
    if not body.get("done") or body.get("done_reason") != "stop":
        raise RuntimeError(
            f"Ollama did not complete generation: {body.get('done')}, {body.get('done_reason')}"
        )
    generated = body.get("response")
    if not isinstance(generated, str) or not generated:
        raise RuntimeError("Ollama response has no JSON response string")
    ret = json.loads(generated)
    if capture_stats:
        stats = {k:body.get(k, -1) for k in STATS_KEYS}
        return ret, stats
    else:
        return ret
