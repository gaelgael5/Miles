from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from miles_socle.contracts import dump, file_write_contracts, published_spec

from miles.app import build_app
from miles.mcp_api.server import MCP_PATH, build_server

# Contrats publiés pour les agents (article docflow terminal-pr « Contrats d'interface ») :
# générés depuis le code, versionnés dans `<produit>/docs/contracts`, et un test vérifie
# qu'ils sont à jour. Écrits à la main, ils divergeraient du service sans que rien ne le
# signale.
#
# Rangés AVEC leur produit depuis le découpage du 27/10/2026 : ces deux-là décrivent la
# surface du portail, et les deux autres produits publieront les leurs.
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
    # L'élagage et la sérialisation sont au socle depuis le 02/11/2026 (deuxième usage :
    # le module d'environnement publie son point d'entrée d'ingestion). Ce qui reste ici
    # est ce que CE produit publie, et ce que son article promet.
    return published_spec(
        build_app().openapi(),
        info={
            "title": "Miles — clés d'API, OAuth et identité d'acteur",
            "version": "1",
            "description": (
                "Routes publiées pour connecter un agent à la surface MCP de Miles"
                f" ({MCP_PATH}). Générées depuis le code ; l'article docflow terminal-pr"
                " « Contrats d'interface » dit ce qui est garanti."
            ),
        },
        prefixes=PUBLISHED_PREFIXES,
    )


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
        OPENAPI_FILE: dump(openapi_contract()),
        MCP_TOOLS_FILE: dump(mcp_tools_contract()),
    }


def main() -> None:
    file_write_contracts(CONTRACTS_DIR, rendered())
