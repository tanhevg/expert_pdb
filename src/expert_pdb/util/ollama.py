import asyncio
import json
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import ollama
import pydantic

log = logging.getLogger(__name__)
# log.setLevel(logging.DEBUG)
SYSTEM_PROMPT = """
    You are a data processing assistant. You must respond with valid JSON only.
    Use the `python` tool if you need to compute anything, but you MUST use the
    `submit_extracted_data` tool to output your final answer. 
"""

STATS_KEYS = ["total_duration", "load_duration", "prompt_eval_count", "prompt_eval_duration", "eval_count", "eval_duration"]
MAX_CHAT_INDEX = 30

class LLMResponse(pydantic.BaseModel):
    response: str
    'LLM Response'

    thinking: str
    'Thinking response'

    tool_calls: Sequence[ollama.Message.ToolCall]
    'Tool calls'

def _save_log(body: str, out_dir: Path, key: str, suffix:str) -> None:
    out_path = out_dir / f"{key}_{suffix}.txt"
    log.info(f"Writing {out_path}")
    with out_path.open("w") as handle:
        handle.write(body)


# git@github.com:alexyslozada/mcp-course.git:clients/ollama-py/ollama-python-app.py
class AsyncOllamaAgent:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        tools: Mapping[str, Callable],
        log_dir: Path | None,
    ):
        self.model = model
        self.ollama_client = ollama.Client(base_url)
        self.tools = tools
        self.ollama_tools = None
        self.log_dir = log_dir

    def check_ollama(self):
        r = self.ollama_client.list()
        for m in r.models:
            if m.model == self.model:
                log.info(f"Connected to Ollama; model {m.model} detected")
                return
        raise RuntimeError(f"Model {self.model} is not available")

    async def start(self):
        await asyncio.to_thread(self.check_ollama)
        self.ollama_tools = [
            ollama._utils.convert_function_to_tool(tool)
            for tool in self.tools.values()
        ]
        # if self.mcp_params:
        #     self.mcp_client = McpClient(**self.mcp_params, tool_selector=self.mcp_selector)
        #     r = await self.mcp_client.connect()
        #     if not r:
        #         raise RuntimeError("Could not connect to MCP")
        #     mcp_tools = await self.mcp_client.list_tools()
        #     mcp_tools = _convert_mcp_tools(mcp_tools)
        # else:
        #     mcp_tools = None
        # extra_tools = [ollama._utils.convert_function_to_tool(t) for t in self.extra_tools.values()]
        # if mcp_tools is None:
        #     self.ollama_tools = extra_tools
        # elif self.extra_tools is None:
        #     self.ollama_tools = mcp_tools
        # else:
        #     self.ollama_tools = mcp_tools + extra_tools
        log.info(f"Tools: {[t['function']['name'] for t in self.ollama_tools]}")

    async def stop(self):
        return None

    def streaming_chat(self, messages:Mapping[str, str]) -> LLMResponse:
        response = self.ollama_client.chat(model=self.model, messages=messages, tools=self.ollama_tools, think=True, stream=True)
        thinking = ''
        content = ''
        tool_calls = []
        for chunk in response:
            if chunk.message.thinking:
                thinking += chunk.message.thinking
                if log.isEnabledFor(logging.DEBUG):
                    log.debug(f"Thinking:\n{chunk.message.thinking}")
            if chunk.message.content:
                content += chunk.message.content
                if log.isEnabledFor(logging.DEBUG):
                    log.debug(f"Response:\n{chunk.message.content}")
            if chunk.message.tool_calls is not None:
                tool_calls.extend(chunk.message.tool_calls)
                if log.isEnabledFor(logging.DEBUG):
                    for tc in chunk.message.tool_calls:
                        log.debug(f"Tool {tc.function.name}({',\n\t'.join(tc.function.arguments)})")
        log.info(f"LLM Response sizes: thinking={len(thinking)}, content={len(content)}, tools={len(tool_calls)}")
        return LLMResponse(response=content, thinking=thinking, tool_calls=tool_calls)
    
    async def chat(self, prompt:str, system_prompt:str, log_key:str) -> str:
        messages = [{'role': 'user', 'content': prompt}]
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        chat_index = 1
        while chat_index <= MAX_CHAT_INDEX:
            llm_response = await asyncio.to_thread(self.streaming_chat, messages)
            lk = f"{log_key}_{chat_index}"
            chat_index += 1
            if llm_response.thinking:
                _save_log(llm_response.thinking, self.log_dir, lk, 'thinking')
            if llm_response.response:
                _save_log(llm_response.response, self.log_dir, lk, 'response')
            if not llm_response.tool_calls:
                return llm_response.response
            messages.append({
                'role': 'assistant', 
                'thinking': llm_response.thinking, 
                'content': llm_response.response, 
                'tool_calls': llm_response.tool_calls
            })
            tool_calls = []
            for tc in llm_response.tool_calls:
                if tc.function.name == 'submit_extracted_data':
                    return tc.function.arguments['s']
                t = {'function':tc.function}
                t['tool_call_id'] = uuid.uuid4()
                tool_calls.append(t)
            _save_log(str(tool_calls), self.log_dir, lk, 'tools')
            tool_results = await self.call_tools(tool_calls)
            messages.extend(tool_results)
        raise RuntimeError(f"Stuck in a loop with tool calls with {MAX_CHAT_INDEX} LLM messages")

    async def call_tools(self, tools):
        tasks: list[asyncio.Task] = []
        async with asyncio.TaskGroup() as tg:
            for t in tools:
                tasks.append(tg.create_task(self.call_tool(t['function']['name'], t['function']['arguments'], t['tool_call_id'])))
        assert all([t.done() for t in tasks])
        return [t.result() for t in tasks if t.result() is not None]

    async def call_tool(self, name, args, tc_id):
        func = self.tools[name]
        try:
            tool_result = await asyncio.to_thread(func, **args)
            ret = {
                "role": 'tool',
                "tool_call_id": tc_id,
                "name": name,
                "content": str(tool_result)
            }
            return ret
        except Exception as e:
            log.error(f"Tool {name} raised an exception", exc_info=e)
            return None

