"""Calls the Phase 2 MCP server over stdio. One server process (one browser) per pipeline run."""
from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Protocol

from ..schemas import SearchResponse


class ScrapeClient(Protocol):
    async def search(self, query: str, max_results: int) -> SearchResponse: ...


class McpScrapeClient:
    def __init__(self, headed: bool = False) -> None:
        self.headed = headed
        self._stack: AsyncExitStack | None = None
        self._session = None

    async def __aenter__(self) -> "McpScrapeClient":
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError:
            raise SystemExit('Needs mcp 1.x: pip install "mcp>=1.10,<2"')
        env = dict(os.environ)  # keep DISPLAY etc. for headed mode
        env["LEADSWEEP_HEADLESS"] = "false" if self.headed else env.get("LEADSWEEP_HEADLESS", "true")
        params = StdioServerParameters(command=sys.executable, args=["-m", "leadsweep.mcp_server"], env=env)
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._stack:
            await self._stack.aclose()

    async def search(self, query: str, max_results: int) -> SearchResponse:
        assert self._session is not None, "use 'async with McpScrapeClient()'"
        res = await self._session.call_tool("search_tweets", {"query": query, "max_results": max_results})
        if getattr(res, "isError", False):
            raise RuntimeError(f"MCP tool error: {res.content[0].text if res.content else 'unknown'}")
        payload = res.structuredContent or json.loads(res.content[0].text)
        return SearchResponse.model_validate(payload)
