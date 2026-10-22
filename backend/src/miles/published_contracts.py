from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from miles.app import build_app
from miles.mcp_api.server import MCP_PATH, build_server

# Contrats publiés pour les agents (article docflow terminal-pr « Contrats d'interface ») :
# générés depuis le code, versionnés dans docs/contracts, et un test vérifie qu'ils sont à
# jour. Écrits à la main, ils divergeraient du service sans que rien ne le signale.
CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts"
OPENAPI_FILE = "miles-agent-access.openapi.json"
MCP_TOOLS_FILE = "miles-mcp-tools.json"
PUBLISHED_PREFIXES = (
    "/api/api-keys",
    "/api/oauth-clients",
    "/api/oauth/authorize",
    "/api/auth/me/oauth-grants",
    "/api/auth/me/identity",
    "/.well-known/",
    "/oauth/token",
)


def openapi_contract() -> dict[str, Any]:
    spec = build_app().openapi()
    spec["info"] = {
        "title": "Miles — clés d'API, OAuth et identité d'acteur",
        "version": "1",
        "description": (
            "Routes publiées pour connecter un agent à la surface MCP de Miles"
            f" ({MCP_PATH}). Générées depuis le code ; l'article docflow terminal-pr"
            " « Contrats d'interface » dit ce qui est garanti."
        ),
    }
    spec["paths"] = {p: v for p, v in spec["paths"].items() if p.startswith(PUBLISHED_PREFIXES)}
    schemas = spec.get("components", {}).get("schemas", {})
    spec["components"] = {"schemas": {k: schemas[k] for k in sorted(_referenced(spec, schemas))}}
    return spec


def mcp_tools_contract() -> dict[str, Any]:
    tools = asyncio.run(build_server().list_tools())
    return {
        "server": "miles",
        "transport": "streamable-http, sans état, réponses JSON",
        "path": MCP_PATH,
        "tools": [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in tools
        ],
    }


def rendered() -> dict[str, str]:
    """Le contenu attendu de chaque fichier publié, à l'octet près."""
    return {
        OPENAPI_FILE: _dump(openapi_contract()),
        MCP_TOOLS_FILE: _dump(mcp_tools_contract()),
    }


def main() -> None:
    for name, content in rendered().items():
        (CONTRACTS_DIR / name).write_text(content, encoding="utf-8")


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _referenced(spec: dict[str, Any], schemas: dict[str, Any]) -> set[str]:
    found: set[str] = set()
    pending: list[Any] = [spec["paths"]]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and (name := ref.rsplit("/", 1)[1]) not in found:
                found.add(name)
                pending.append(schemas.get(name, {}))
            pending.extend(v for k, v in node.items() if k != "$ref")
        elif isinstance(node, list):
            pending.extend(node)
    return found
