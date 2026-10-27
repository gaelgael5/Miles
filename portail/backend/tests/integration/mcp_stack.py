from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from miles.obo.signature import sign_actor
from tests.integration.test_api_keys_pg import ACCEPT, MCP, running_mcp
from tests.integration.work_stack import Forge, open_work_forge

# Identité d'acteur de l'administrateur auprès du portail (OBO, story 52ac5782).
ADMIN_GUID = "7c9e6679-7425-40de-944b-e07fc1f90ae7"


@dataclass
class McpForge:
    """La forge de l'atelier, une clé d'écriture sur « retrait », et un client MCP.

    Par défaut, chaque appel est signé pour l'administrateur (OBO), qui a la main sur
    « edition » : une écriture MCP agit comme la personne (9def0adc).
    """

    forge: Forge
    mcp: httpx.AsyncClient
    secret: str
    key_id: str

    def signed(self, guid: str = ADMIN_GUID) -> dict[str, str]:
        at = int(time.time())
        return {
            "x-portal-actor": guid,
            "x-portal-actor-timestamp": str(at),
            "x-portal-actor-signature": sign_actor(guid, at, self.secret),
        }

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
        headers = headers or {}
        # Un autre jeton (autre clé, OAuth) appelle pour lui-même : pas de signature ajoutée.
        mine = {} if "Authorization" in headers else self.signed()
        sent = ACCEPT | {"Authorization": f"Bearer {self.secret}"} | mine | headers
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
        linked = await forge.client.put("/api/auth/me/identity", json={"actor": ADMIN_GUID})
        assert linked.status_code == 200, linked.text
        async with running_mcp(forge.portal), forge.portal.anonymous() as mcp:
            yield McpForge(forge, mcp, issued["secret"], issued["key"]["id"])
