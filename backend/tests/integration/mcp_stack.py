from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from tests.integration.test_api_keys_pg import ACCEPT, MCP, running_mcp
from tests.integration.work_stack import Forge, open_work_forge


@dataclass
class McpForge:
    """La forge de l'atelier, une clé d'écriture sur « retrait », et un client MCP."""

    forge: Forge
    mcp: httpx.AsyncClient
    secret: str
    key_id: str

    async def call(
        self, tool: str, arguments: dict[str, Any], headers: dict[str, str] | None = None
    ) -> tuple[bool, Any]:
        """(erreur, contenu) : le refus structuré, ou le résultat de l'outil."""
        message = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        sent = ACCEPT | {"Authorization": f"Bearer {self.secret}"} | (headers or {})
        response = await self.mcp.post(MCP, json=message, headers=sent, timeout=120)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        if result.get("isError"):
            # Le SDK préfixe le texte d'un refus : « Error executing tool <nom>: <json> ».
            text = result["content"][0]["text"]
            prefix = f"Error executing tool {tool}: "
            assert text.startswith(prefix), text
            return True, json.loads(text.removeprefix(prefix))
        content = result["structuredContent"]
        return False, content["result"] if list(content) == ["result"] else content

    async def ok(self, tool: str, arguments: dict[str, Any], **kw: Any) -> Any:
        failed, content = await self.call(tool, arguments, **kw)
        assert not failed, content
        return content

    async def refused(self, tool: str, arguments: dict[str, Any], **kw: Any) -> Any:
        failed, content = await self.call(tool, arguments, **kw)
        assert failed, content
        return content


async def issue_key(forge: Forge, grants: dict[str, str], label: str = "Gateway") -> Any:
    body = {"label": label, "grants": [{"workspace_id": w, "access": a} for w, a in grants.items()]}
    issued = await forge.client.post("/api/api-keys", json=body)
    assert issued.status_code == 201, issued.text
    return issued.json()


@asynccontextmanager
async def open_mcp_forge(blank_db: str, tmp_path: Path) -> AsyncIterator[McpForge]:
    async with open_work_forge(blank_db, tmp_path) as forge:
        issued = await issue_key(forge, {"retrait": "ecriture"})
        async with running_mcp(forge.portal), forge.portal.anonymous() as mcp:
            yield McpForge(forge, mcp, issued["secret"], issued["key"]["id"])
