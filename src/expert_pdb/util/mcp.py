# lifted from git@github.com:alexyslozada/mcp-course.git:clients/ollama-py/mcp_client.py
import logging
from mcp import ClientSession, StdioServerParameters, ListToolsResult
from mcp.client.stdio import stdio_client
from typing import Optional, Dict, Any, Tuple, Union
import json
import os

# Configurar logging
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


MCP_PARAMS = {
    'command': 'node',
    "args": ["/Users/evgeny/code/NCBI-Datasets-MCP-Server/build/index.js"],
    "env": {
        "NCBI_API_KEY": os.environ['NCBI_API_KEY'] # https://account.ncbi.nlm.nih.gov/settings/
    }
}

MCP_SELECTOR = ['foobar']
# MCP_SELECTOR = ['get_sequence_data', 'get_gene_info', 'get_protein_info']

def _convert_mcp_tools(tools):
    return [
        {
            'type': 'function',
            'function': {
                'name': f"mcp_ncbi_{t.name}",
                'description': getattr(t, 'description', f"MCP tool: {t.name}"),
                'parameters': getattr(t, 'input_schema', {'type': 'object'})
            }
        } for t in tools
    ]


class McpClient:
    
    def __init__(self, command: str, args: list[str], env: Optional[Dict[str, str]] = None, 
                 tool_selector:list[str]|None=None,):
        self.server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env
        )
        self.session = None
        self.read = None
        self.write = None
        self._client_ctx = None
        self._session_ctx = None
        self.tool_selector = tool_selector

    async def connect(self) -> bool:
        try:
            self._client_ctx = stdio_client(self.server_params)
            client = await self._client_ctx.__aenter__()
            self.read, self.write = client
            self._session_ctx = ClientSession(self.read, self.write)
            self.session = await self._session_ctx.__aenter__()
            await self.session.initialize()
            log.info("MCP stdio connection established")
            return True
        except ConnectionError as e:
            log.error(f"Error establishing MCP stdio connection", exc_info=e)
            await self.disconnect()
            return False
        except Exception as e:
            log.error(f"Error establishing MCP stdio connection", exc_info=e)
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        try:
            if self._session_ctx:
                await self._session_ctx.__aexit__(None, None, None)
                self._session_ctx = None
                self.session = None
            
            if self._client_ctx:
                await self._client_ctx.__aexit__(None, None, None)
                self._client_ctx = None
                self.read = None
                self.write = None
            
            log.info("Disconnected from MCP server")
        except Exception as e:
            log.error(f"Error disconnecting from MCP", exc_info=e)

    async def list_tools(self) -> Any:
        if not self.session:
            raise RuntimeError("Not connected to MCP")
        try:
            tools = await self.session.list_tools()
            log.debug(f"MCP tools:\n{'\n'.join(sorted([t.name for t in tools.tools]))}")
            tools = [t for t in tools.tools if not self.tool_selector or t.name in self.tool_selector]
            for t in tools:
                log.debug(t)
            return tools
        except Exception as e:
            log.error(f"Error getting tools from MCP", exc_info=e)
            raise

    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if not self.session:
            raise RuntimeError("Not connected to MCP")
        try:
            if log.isEnabledFor(logging.DEBUG):
                log.debug(f"Executing tool {tool_name} with arguments {arguments}")
            result = await self.session.call_tool(tool_name, arguments)
            if log.isEnabledFor(logging.DEBUG):
                log.debug(f"Results from tool {tool_name}: {result}")
            return result
        except Exception as e:
            log.error(f"Error executing MCP tool {tool_name}", exc_info=e)
            raise

    async def __aenter__(self) -> 'McpClient':
        success = await self.connect()
        if not success:
            raise RuntimeError("Error establishing MCP connection")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()
