import asyncio
import logging

import pytest

from expert_pdb.util import ollama
from expert_pdb.util.ollama import AsyncOllamaAgent, LLMResponse


def test_call_tools_returns_only_successful_results_and_logs_failures(
    caplog,
):
    agent = AsyncOllamaAgent.__new__(AsyncOllamaAgent)

    def successful_tool(result: str) -> str:
        return result

    def failing_tool() -> None:
        raise RuntimeError("tool failure")

    agent.tools = {
        "first_tool": successful_tool,
        "failing_tool": failing_tool,
        "last_tool": successful_tool,
    }
    tools = [
        {
            "function": {"name": "first_tool", "arguments": {"result": "first"}},
            "tool_call_id": "call-1",
        },
        {
            "function": {"name": "failing_tool", "arguments": {}},
            "tool_call_id": "call-2",
        },
        {
            "function": {"name": "last_tool", "arguments": {"result": "last"}},
            "tool_call_id": "call-3",
        },
    ]

    with caplog.at_level(logging.ERROR, logger="expert_pdb.util.ollama"):
        results = asyncio.run(agent.call_tools(tools))

    assert [result["name"] for result in results] == ["first_tool", "last_tool"]
    assert "Tool failing_tool raised an exception" in caplog.text
    assert "RuntimeError: tool failure" in caplog.text


def test_chat_stops_after_max_chat_index(monkeypatch, tmp_path):
    agent = AsyncOllamaAgent.__new__(AsyncOllamaAgent)
    agent.log_dir = tmp_path
    chat_count = 0

    def streaming_chat(messages):
        nonlocal chat_count
        chat_count += 1
        return LLMResponse(
            response="",
            thinking="",
            tool_calls=[
                {
                    "function": {
                        "name": "python",
                        "arguments": {"code": "print('hello world')"},
                    },
                    "tool_call_id": "call-1",
                }
            ],
        )

    async def call_tool(name, args, tc_id):
        return {
            "role": "tool",
            "tool_call_id": tc_id,
            "name": name,
            "content": "hello world",
        }

    monkeypatch.setattr(agent, "streaming_chat", streaming_chat)
    monkeypatch.setattr(agent, "call_tool", call_tool)

    async def run_chat():
        return await asyncio.wait_for(
            agent.chat("prompt", "system prompt", log_key="test"),
            timeout=5,
        )

    expected_message = (
        f"Stuck in a loop with tool calls with {ollama.MAX_CHAT_INDEX} LLM messages"
    )
    with pytest.raises(RuntimeError, match=expected_message):
        asyncio.run(run_chat())

    assert chat_count == ollama.MAX_CHAT_INDEX
