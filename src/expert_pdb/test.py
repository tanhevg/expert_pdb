import xml.etree.ElementTree as ET
import ollama
import random
import sys


import asyncio
from datetime import datetime
import uuid

import json
import pathlib
import logging

from util.ollama import OllamaAgent
from util.mcp import McpClient, _convert_mcp_tools
from util.agentic_tools import call_python


def parse_body(root_el:ET.Element):
    body = root_el.find('./body')
    assert body is not None
    ret = ET.tostring(body, method='xml')
    print(ret)
    return ret

def parse_abstract(root_el:ET.Element):
    abstract = root_el.find('.//abstract')
    if abstract is None:
        return None
    ret = ET.tostring(abstract, method='xml')
    print(ret)
    return ret

def main1():
    filename = '/Users/evgeny/nobackup/expert_pdb/publications/PMC5940772.1/PMC5940772.1.xml'
    jats_root = ET.parse(filename).getroot()
    # body = parse_body(jats_root)
    # abstract = parse_abstract(jats_root)
    body = jats_root.find('./body')
    abstract = jats_root.find('.//abstract')
    short_article = ET.Element('short_article')
    short_article.append(abstract)
    short_article.append(body)
    ET.indent(short_article, ' '*4)
    xml_str = ET.tostring(short_article, 'utf8', method='xml')
    print(xml_str.decode('utf8'))


ollama_tools = {
    'call_python': call_python
}

def main():
    # exec('print("hello world!")')
    ollama_client = ollama.Client("http://codon-gpu-010:11434")
    random_sequence = [random.random() for _ in range(100)]
    prompt =f"""
    Write a Python function that implements tree sort and sort the following array:
    {random_sequence}
    """
    print(f"Prompt: {prompt}")

    messages = [{"role": "user", "content": prompt}]

    # pass functions directly as tools in the tools list or as a JSON schema
    response = ollama_client.chat(model="qwen3.8:27b", messages=messages, tools=[call_python], think=True, stream=True)

    thinking = ''
    content = ''
    tool_results = []
    for chunk in response:
        if chunk.message.thinking:
            # accumulate the partial thinking
            thinking += chunk.message.thinking
        elif chunk.message.content:
            # accumulate the partial content
            content += chunk.message.content
        if chunk.message.tool_calls is not None:
            for tc in chunk.message.tool_calls:
                if tc.function.name in ollama_tools:
                    print(f"Calling {tc.function.name} with arguments {tc.function.arguments.keys()}")
                    result = ollama_tools[tc.function.name](**tc.function.arguments)
                    tool_results.append(result)
    print(f"Thinking:\n{thinking}")
    print(f"Response:\n{content}")
    assert len(tool_results) == 1
    assert len(tool_results[0]) == 3
    assert tool_results[0]['return_code'] == 0
    print(tool_results[0]['stdout'])
    assert tool_results[0]['stderr'] == ''
    print(f"Tool results:\n{tool_results}")

def main2():
    t = ollama._utils.convert_function_to_tool(call_python)
    print(t)

def main3():
    print(uuid.uuid4())
    random_sequence = [int(round(random.random() * 10)) + 1 for _ in range(10)]
    print("Longest to wait:", max(*random_sequence))
    
    async def _f(i):
        await asyncio.sleep(random_sequence[i])
        return (random_sequence[i] - 1) / 10

    async def _g():
        tasks: list[asyncio.Task] = []
        print(datetime.now())
        async with asyncio.TaskGroup() as tg:
            for i in range(10):
                t = tg.create_task(_f(i))
                tasks.append(t)
        print(datetime.now())
        for t in tasks:
            assert t.done()
        return[t.result() for t in tasks]

    res = asyncio.run(_g())
    print(res)

def main4():
    mcp_params = {
        'command': 'node',
        "args": ["/Users/evgeny/code/NCBI-Datasets-MCP-Server/build/index.js"],
        "env": {
            "NCBI_API_KEY": "fe19c39d7140f4499d88c5f0faba5fb0f608"
        }
    }
    mcp_client = McpClient(**mcp_params)
    async def _test_client():
        async with mcp_client:
            tools = await mcp_client.list_tools()
            return tools
    tools = asyncio.run(_test_client())
    tools = _convert_mcp_tools(tools, ['get_sequence_data'])
    print(len(tools))
    json.dump(tools, sys.stdout, ensure_ascii=False, indent=4)

import time

def main5():
    mcp_params = {
            'command': 'node',
            "args": ["/Users/evgeny/code/NCBI-Datasets-MCP-Server/build/index.js"],
            "env": {
                "NCBI_API_KEY": "fe19c39d7140f4499d88c5f0faba5fb0f608"
            }
        }
    def _test_connect(client:McpClient):
        return await client.connect()
    
    def _test_disconnect(client:McpClient):
        return await client.disconnect()

    async def _test_loop():
        mcp_client = McpClient(**mcp_params)
        connect_result = _test_connect(mcp_client)
        print(connect_result)
        time.sleep(10)
        disconnect_result = _test_disconnect(mcp_client)
        print(disconnect_result)
    asyncio.run(_test_loop())
    
def configure_logging() -> None:
    config_path = pathlib.Path(__file__).resolve().parents[2] / "log.cfg"
    logging.config.fileConfig(config_path, disable_existing_loggers=False)

if __name__ == '__main__':
    configure_logging()
    main5()