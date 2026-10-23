from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.contracts.reading import Contract
from miles.git.snapshot import CommitNotFoundError
from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.mcp_api.tools_models import ReadBranch, Workspace
from miles.transform.catalog import functions_catalog
from miles.transform.engine import function_registry
from miles.workshop.domains import DomainNotFoundError, Element
from miles.workshop.targeted import ContractUnknownError, TargetedReads
from miles.workspaces.model import WorkspaceInputError

Commit = Annotated[
    str | None,
    Field(
        description=(
            "Identifiant complet (40 caractères) d'un commit de la branche : lit l'état à ce"
            " commit, pas l'état courant. Absent : la tête de la branche."
        )
    ),
]
After = Annotated[
    str | None,
    Field(
        description=(
            "Pour reprendre une réponse tronquée : le `next_after` qu'elle a rendu. Les"
            " éléments suivants, par ordre de chemin, sont alors rendus."
        )
    ),
]
Domain = Annotated[str, Field(description="Nom du domaine (voir list_domains).")]
ContractSlug = Annotated[str, Field(description="Slug du contrat (voir list_contracts).")]


def _reads(caller: Caller) -> TargetedReads:
    reads: TargetedReads = caller.services.targeted_reads
    return reads


def _refused(exc: Exception) -> Exception:
    """Les refus propres aux lectures ciblées, puis ceux communs à toute primitive."""
    if isinstance(exc, CommitNotFoundError):
        return ToolError(refusal("commit_inconnu", commit=str(exc)))
    if isinstance(exc, ContractUnknownError):
        return ToolError(refusal("contrat_inconnu", contrat=exc.slug, existants=exc.existing))
    if isinstance(exc, WorkspaceInputError) and exc.field == "domaine":
        return ToolError(refusal("champ_invalide", champ="domaine", raison=exc.reason))
    return tool_refusal(exc) or exc


def _elements(elements: list[Element]) -> list[dict[str, Any]]:
    return [{"path": e.path, "content": e.content} for e in elements]


def _contract(contract: Contract) -> dict[str, Any]:
    meta = contract.meta
    return {
        "slug": meta.slug,
        "label": meta.label,
        "sens": meta.direction,
        "versions": [
            {
                "number": v.number,
                # None : fichier devenu illisible hors de Miles.
                "title": None if v.parsed is None else v.parsed.title,
                "openapi": None if v.parsed is None else v.parsed.openapi,
                "operations": None if v.parsed is None else len(v.parsed.operations),
                # Modèles dérivés présents dans git, et leur état face au fichier.
                "models": [] if v.models is None else list(v.models.present),
                "models_state": None if v.models is None else v.models.state,
            }
            for v in contract.versions
        ],
    }


def register(server: MCPServer) -> None:
    @server.tool(description="Liste les domaines d'une branche, à sa tête ou à un commit.")
    async def list_domains(
        workspace_id: Workspace,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
        commit: Commit = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            at, names = await _reads(caller).resolve_domains(
                caller.viewer, workspace_id, branch, commit
            )
        except Exception as exc:
            raise _refused(exc) from None
        return {"commit": at, "domains": names}

    @server.tool(
        description=(
            "Rend tout un domaine en un appel : messages, mappings entrants et sortants,"
            " référentiels, composants, écrans, scénarios, chacun avec son chemin et son"
            " contenu. `misplaced` : fichiers du domaine hors de ces rubriques. Réponse"
            " bornée : si `truncated`, les éléments au contenu null se redemandent avec"
            " after = next_after. Domaine inconnu : refus domaine_inconnu avec la liste."
        )
    )
    async def get_domain(
        workspace_id: Workspace,
        domain: Domain,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
        commit: Commit = None,
        after: After = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            at, content = await _reads(caller).resolve_domain(
                caller.viewer, workspace_id, domain, branch, commit, after
            )
        except DomainNotFoundError as exc:
            raise ToolError(
                refusal("domaine_inconnu", domaine=exc.name, existants=exc.existing)
            ) from None
        except Exception as exc:
            raise _refused(exc) from None
        return {
            "commit": at,
            "domain": content.name,
            "sections": {name: _elements(items) for name, items in content.sections.items()},
            "misplaced": _elements(content.misplaced),
            "truncated": content.truncated,
            "next_after": content.next_after,
        }

    @server.tool(
        description=(
            "Rend les messages pivot transverses (shared/messages), chemin et contenu. Même"
            " borne que get_domain : si `truncated`, reprendre avec after = next_after."
        )
    )
    async def get_shared_messages(
        workspace_id: Workspace,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
        commit: Commit = None,
        after: After = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            at, page = await _reads(caller).resolve_shared_messages(
                caller.viewer, workspace_id, branch, commit, after
            )
        except Exception as exc:
            raise _refused(exc) from None
        return {
            "commit": at,
            "messages": _elements(page.elements),
            "truncated": page.truncated,
            "next_after": page.next_after,
        }

    @server.tool(description="Liste les contrats d'une branche avec leurs versions intégrées.")
    async def list_contracts(
        workspace_id: Workspace,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
        commit: Commit = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            at, contracts = await _reads(caller).resolve_contracts(
                caller.viewer, workspace_id, branch, commit
            )
        except Exception as exc:
            raise _refused(exc) from None
        return {"commit": at, "contracts": [_contract(c) for c in contracts]}

    @server.tool(
        description=(
            "Rend un contrat et ses versions — `sens` : « sortant » pour un contrat externe"
            " (appel d'un service distant), « entrant » pour un contrat interne (webhook"
            " reçu). Avec `version`, les opérations de cette"
            " version (méthode, chemin, operationId) et ses modèles dérivés (un JSON Schema"
            " par schéma du contrat, en lecture seule), bornés : si `truncated`, redemander"
            " avec after = next_after. Refus : contrat_inconnu ou version_inconnue, avec ce"
            " qui existe."
        )
    )
    async def get_contract(
        workspace_id: Workspace,
        contract: ContractSlug,
        ctx: Context[Any, Request],
        version: Annotated[int | None, Field(description="Numéro de version.")] = None,
        branch: ReadBranch = None,
        commit: Commit = None,
        after: After = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            at, found, models = await _reads(caller).resolve_contract(
                caller.viewer, workspace_id, contract, branch, commit, version, after
            )
        except Exception as exc:
            raise _refused(exc) from None
        described = {"commit": at} | _contract(found)
        if version is None:
            return described
        chosen = next((v for v in found.versions if v.number == version), None)
        if chosen is None:
            existing = [v.number for v in found.versions]
            raise ToolError(refusal("version_inconnue", version=version, existantes=existing))
        operations = None
        if chosen.parsed is not None:
            operations = [
                {"method": o.method, "path": o.path, "operation_id": o.operation_id}
                for o in chosen.parsed.operations
            ]
        page = {"elements": [], "truncated": False, "next_after": None}
        if models is not None:
            page = {
                "elements": _elements(models.elements),
                "truncated": models.truncated,
                "next_after": models.next_after,
            }
        return described | {
            "version": version,
            "operations": operations,
            "models": page["elements"],
            "truncated": page["truncated"],
            "next_after": page["next_after"],
        }

    @server.tool(
        description=(
            "Rend le catalogue d'une branche : fonctions utilisables dans un template (avec"
            " signature et documentation), modèles de données avec leurs propriétés, et"
            " plancher d'application, à la tête ou à un commit."
        )
    )
    async def get_catalog(
        workspace_id: Workspace,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
        commit: Commit = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            found = await caller.services.template_catalog.resolve(
                caller.viewer, workspace_id, branch, commit
            )
        except Exception as exc:
            raise _refused(exc) from None
        functions = [
            {
                "name": f.name,
                "signature": f.signature,
                "description": f.description,
                "documentation": f.documentation,
                "parameters": list(f.parameters),
                "returns": f.returns,
                "complete": not f.missing,
            }
            for f in functions_catalog(function_registry())
        ]
        models = [
            {
                "scope": m.scope,
                "name": m.name,
                "path": m.path,
                "properties": None if m.properties is None else list(m.properties),
            }
            for m in found["models"]
        ]
        return {
            "commit": found["commit"],
            "app_floor": found["app_floor"],
            "functions": functions,
            "models": models,
        }
