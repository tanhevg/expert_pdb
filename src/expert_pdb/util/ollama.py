import requests
import json
from typing import Any, Optional
import logging
from pathlib import Path

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)
SYSTEM_PROMPT = """
    You are a data processing assistant. You must respond with valid JSON only. 
"""

def preflight_ollama(base_url: str) -> None:
    response = requests.get(base_url.rstrip("/") + "/api/tags", timeout=15)
    response.raise_for_status()

def ollama_json(base_url: str, model: str, prompt: str, pmcid:str, out_dir:Optional[Path]=None) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/api/generate"
    if log.isEnabledFor(logging.DEBUG):
        log.debug(f"Prompting model {model} at {base_url} with\n{prompt}")
    request_body = {
        "model": model, 
        "prompt": prompt, 
        "stream": False,
        "system": SYSTEM_PROMPT, 
        # "format": "json",
        "options": {
            "num_ctx": 262144,
            "num_predict": 65536,
        },
        "keep_alive": -1
    }
    response = requests.post(url, json=request_body, timeout=600)
    if log.isEnabledFor(logging.DEBUG):
        log.debug(f"Raw response:\n {response}\n{response.text}")
    response.raise_for_status()
    body = response.json()
    if out_dir:
        out_path = out_dir / f"{pmcid}_ollama_full.json"
        with out_path.open('w') as f:
            json.dump(body, f)
    assert body.get('done') and body.get('done_reason') == 'stop',\
        f"Ollama errorred when handling this query: {body.get('done')}, {body.get('done_reason')}"
    generated = body.get("response")
    if not isinstance(generated, str) or not generated:
        log.error(f"Error decoding response {response.text}")
        raise Exception("Ollama response has no JSON response string")
    try:
        return json.loads(generated)
    except json.JSONDecodeError as e:
        log.error(f"Error decoding response {response.text}")
        raise e
    