import json
import logging
from pathlib import Path
from typing import Any

import ollama

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)
SYSTEM_PROMPT = """
    You are a data processing assistant. You must respond with valid JSON only. 
"""

STATS_KEYS = ["total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration"]


def preflight_ollama(base_url: str) -> None:
    ollama.list()


def _save_response(body: str, out_dir: Path | None, pmcid: str, suffix:str) -> None:
    out_path = out_dir / f"{pmcid}_{suffix}.txt"
    with out_path.open("w") as handle:
        handle.write(body)


def ollama_json(
    base_url: str,
    model: str,
    prompt: str,
    pmcid: str,
    out_dir: Path | None = None,
) -> Any:
    if log.isEnabledFor(logging.DEBUG):
        log.debug("Prompting model %s at %s", model, base_url)
    messages = ollama.generate(model=model, prompt=prompt, think=True, stream=True, system=SYSTEM_PROMPT, 
                               options={'temperature':0})
    thinking_response = ""
    response = ""
    full_response = ""
    response_list = []
    for m in messages:
        response_list.append(m)
        full_response += str(m)
        if 'thinking' in m:
            thinking_response += m['thinking']
        if 'response' in m:
            response += m['response']
    _save_response(full_response, out_dir, pmcid, 'full')
    _save_response(response, out_dir, pmcid, 'response')
    _save_response(thinking_response, out_dir, pmcid, 'thinking')
    log.debug(f"Loading json from response:\n{response}")
    ret = json.loads(response)
    return ret
