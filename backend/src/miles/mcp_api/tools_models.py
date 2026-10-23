from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.datamodels.layout import ModelEntry
from miles.datamodels.service import DataModelsService, ModelNotFoundError
from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.workshop.domains_service import DomainsService

Workspace = Annotated[str, Field(description="Identifiant du workspace (voir list_workspaces).")]
ReadBranch = Annotated[
    str | None,
    Field(description="Slug de la branche à lire ; absent : la branche de base du workspace."),
]
WriteBranch = Annotated[
    str | None,
    Field(
        description=(
            "Slug d'une branche ENFANT du workspace, obligatoire : la branche de base est en"
            " lecture seule. Le refus liste les branches enfants existantes. La personne pour"
            " qui vous appelez doit y avoir la main (refus prise_de_main_requise sinon) ; la"
            " modification reste locale jusqu'à publish_branch."
        )
    ),
]
Scope = Annotated[
    str,
    Field(
        description=(
            "« shared » pour un modèle transverse, sinon le nom d'un domaine existant"
            " (list_domains ; create_domain pour en ajouter un)."
        )
    ),
]
DomainName = Annotated[
    str,
    Field(description="Nom du domaine : minuscules, chiffres, - et _ (63 caractères au plus)."),
]
Name = Annotated[str, Field(description="Nom du modèle (celui de son fichier, sans extension).")]
Content = Annotated[
    str,
    Field(
        description=(
            "Le modèle : un JSON Schema 2020-12 écrit en YAML, dont la racine est un objet"
            " (type: object). `title` est son label. `$schema` et `$id` sont posés par Miles."
            " Un autre modèle se désigne par $ref: miles:/shared/<nom> ou"
            " miles:/domains/<domaine>/<nom>."
        )
    ),
]


def _entry(entry: ModelEntry) -> dict[str, str]:
    return {"scope": entry.scope, "name": entry.name, "path": entry.path}


def _written(entry: ModelEntry, commit: str | None) -> dict[str, Any]:
    # Rejeu à l'identique (critère 5) : rien d'écrit, et la réponse le dit.
    return _entry(entry) | {"commit": commit, "unchanged": commit is None}


async def _models(caller: Caller) -> DataModelsService:
    service: DataModelsService = caller.services.data_models
    return service


async def _unknown(caller: Caller, workspace_id: str, branch: str | None, path: str) -> ToolError:
    """Un modèle inconnu, avec ce qui existe : l'agent se corrige sans appel exploratoire."""
    existing = await (await _models(caller)).resolve_list(
        caller.viewer, workspace_id, branch=branch
    )
    return ToolError(refusal("modele_inconnu", path=path, existants=[e.path for e in existing]))


def register(server: MCPServer) -> None:
    @server.tool(description="Liste les modèles de données d'une branche, avec leur emplacement.")
    async def list_data_models(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, str]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            entries = await (await _models(caller)).resolve_list(
                caller.viewer, workspace_id, branch=branch
            )
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [_entry(e) for e in entries]

    @server.tool(description="Lit un modèle de données : son emplacement et son YAML tel quel.")
    async def get_data_model(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
    ) -> dict[str, str]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        service = await _models(caller)
        try:
            entry, content = await service.resolve_get(
                caller.viewer, workspace_id, scope, name, branch=branch
            )
        except ModelNotFoundError as exc:
            raise await _unknown(caller, workspace_id, branch, str(exc)) from None
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return _entry(entry) | {"content": content}

    @server.tool(
        description=(
            "Crée un modèle de données (JSON Schema 2020-12 en YAML) dans une branche enfant."
            " Refus structurés : yaml_invalide, modele_non_conforme (tous les écarts), nom_pris,"
            " domaine_inconnu (le domaine se crée d'abord par create_domain)."
        )
    )
    async def create_data_model(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _models(caller)

        async def run(author: Any) -> dict[str, Any]:
            entry, commit = await service.resolve_create(
                author, workspace_id, scope, name, content, branch=branch
            )
            return _written(entry, commit)

        element = f"{scope}/{name}"
        return await caller.write("create_data_model", workspace_id, branch, element, run)

    @server.tool(
        description=(
            "Remplace le schéma d'un modèle existant, dans une branche enfant. Le nom ne change"
            " pas : renommer, c'est créer puis supprimer. La version monte de 1, tenue par Miles."
        )
    )
    async def replace_data_model(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _models(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                entry, commit = await service.resolve_replace(
                    author, workspace_id, scope, name, content, branch=branch
                )
            except ModelNotFoundError as exc:
                raise await _unknown(caller, workspace_id, branch, str(exc)) from None
            return _written(entry, commit)

        element = f"{scope}/{name}"
        return await caller.write("replace_data_model", workspace_id, branch, element, run)

    @server.tool(
        description=(
            "Supprime un modèle d'une branche enfant. Refusé (modele_utilise) tant qu'un autre"
            " modèle le désigne : le refus nomme lesquels."
        )
    )
    async def delete_data_model(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _models(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                commit = await service.resolve_delete(
                    author, workspace_id, scope, name, branch=branch
                )
            except ModelNotFoundError as exc:
                raise await _unknown(caller, workspace_id, branch, str(exc)) from None
            return {"deleted": f"{scope}/{name}", "commit": commit}

        element = f"{scope}/{name}"
        return await caller.write("delete_data_model", workspace_id, branch, element, run)

    @server.tool(
        description=(
            "Ajoute un domaine (répertoire domains/<nom>/) dans une branche enfant. Un modèle"
            " de domaine ne peut se créer que dans un domaine existant. Déjà là : sans effet."
        )
    )
    async def create_domain(
        workspace_id: Workspace,
        name: DomainName,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service: DomainsService = caller.services.domains

        async def run(author: Any) -> dict[str, Any]:
            commit = await service.resolve_add(author, workspace_id, name, branch=branch)
            return {"domain": name, "commit": commit, "unchanged": commit is None}

        return await caller.write("create_domain", workspace_id, branch, name, run)
