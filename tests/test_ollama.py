import asyncio
import logging

from expert_pdb.util.ollama import AsyncOllamaAgent


def test_call_tools_returns_only_successful_results_and_logs_failures(
    monkeypatch,
    caplog,
):
    agent = AsyncOllamaAgent.__new__(AsyncOllamaAgent)

    async def call_tool(name, args, tc_id):
        if name == "failing_tool":
            raise RuntimeError("tool failure")
        return {
            "role": "tool",
            "tool_call_id": tc_id,
            "name": name,
            "content": args["result"],
        }

    monkeypatch.setattr(agent, "call_tool", call_tool)
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
    assert "Tool failing_tool failed" in caplog.text
    assert "RuntimeError: tool failure" in caplog.text
