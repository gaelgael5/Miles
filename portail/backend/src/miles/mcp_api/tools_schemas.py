"""Les schémas du paramétrage : les modèles de données, et eux seuls.

Deux familles ont cohabité ici du 11/11/2026 au 14/11/2026, un argument `kind` disant
laquelle. La famille « événement » a disparu avec ce qui la fondait : un type d'event
n'est plus un document mais une DÉCLARATION (voir `tool_args.py`). `kind` est donc
retiré de ces primitives — RUPTURE ASSUMÉE, annoncée comme telle, parce qu'un argument à
une seule valeur admise fait choisir entre une chose et rien.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field
from starlette.requests import Request

from miles.datamodels.service import ModelNotFoundError
from miles.mcp_api.calls import caller_of, tool_refusal
from miles.mcp_api.tool_args import (
    Name,
    ReadBranch,
    Scope,
    Workspace,
    WriteBranch,
    entry_out,
    unknown,
    written_out,
)
from miles.workflowevents.schema import socle_schema
from miles.workshop.domains_service import DomainsService

DomainName = Annotated[
    str,
    Field(description="Nom du domaine : minuscules, chiffres, - et _ (63 caractères au plus)."),
]
Content = Annotated[
    str,
    Field(
        description=(
            "Le schéma : un JSON Schema 2020-12 écrit en YAML, dont la racine est un objet"
            " (type: object). `title` est son label. `$schema` et `$id` sont posés par Miles."
            " Un autre modèle se désigne par $ref: miles:/shared/<nom> ou"
            " miles:/domains/<domaine>/<nom>. Un modèle qu'un TYPE D'EVENT désigne décrit les"
            " seules données MÉTIER : le moteur valide en plus un socle commun"
            " (get_event_base), dont les propriétés ne se redéclarent pas, et"
            " `additionalProperties: false` y est refusé parce qu'il rendrait tout payload"
            " réel invalide."
        )
    ),
]


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Liste les modèles de données d'une branche, avec leur emplacement. Un modèle"
            " sert indifféremment un storage, une source ou le payload d'un type d'event :"
            " c'est la déclaration qui le désigne qui en fait un type d'event."
        )
    )
    async def list_schemas(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, str]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        service = caller.services.data_models
        try:
            entries = await service.resolve_list(caller.viewer, workspace_id, branch=branch)
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [entry_out(e) for e in entries]

    @server.tool(description="Lit un schéma : son emplacement et son YAML tel quel.")
    async def get_schema(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
    ) -> dict[str, str]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            entry, content = await caller.services.data_models.resolve_get(
                caller.viewer, workspace_id, scope, name, branch=branch
            )
        except ModelNotFoundError:
            raise await unknown(caller, workspace_id, branch, scope, name) from None
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return entry_out(entry) | {"content": content}

    @server.tool(
        description=(
            "Crée un modèle dans une branche enfant. Refus structurés : yaml_invalide,"
            " modele_non_conforme (tous les écarts), nom_pris, domaine_inconnu (le domaine se"
            " crée d'abord par create_domain)."
        )
    )
    async def create_schema(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = caller.services.data_models

        async def run(author: Any) -> dict[str, Any]:
            entry, commit = await service.resolve_create(
                author, workspace_id, scope, name, content, branch=branch
            )
            return written_out(entry, commit)

        return await caller.write("create_schema", workspace_id, branch, f"{scope}/{name}", run)

    @server.tool(
        description=(
            "Remplace le schéma ENTIER d'un élément existant, dans une branche enfant. Pour"
            " ne changer qu'une propriété, préférer set_schema_property : l'artefact est plus"
            " petit, et ce qu'il ne nomme pas ne peut pas disparaître. Le nom ne change pas :"
            " renommer, c'est créer puis supprimer. La version monte de 1, tenue par Miles."
        )
    )
    async def replace_schema(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)

        async def run(author: Any) -> dict[str, Any]:
            try:
                entry, commit = await caller.services.data_models.resolve_replace(
                    author, workspace_id, scope, name, content, branch=branch
                )
            except ModelNotFoundError:
                raise await unknown(caller, workspace_id, branch, scope, name) from None
            return written_out(entry, commit)

        return await caller.write("replace_schema", workspace_id, branch, f"{scope}/{name}", run)

    @server.tool(
        description=(
            "Supprime un modèle d'une branche enfant. Un modèle encore désigné est refusé"
            " (modele_utilise) : le refus nomme ce qui le désigne — un autre modèle par un"
            " $ref, ou l'artefact d'un périmètre dont un DEFINE EVENT le prend pour payload."
        )
    )
    async def delete_schema(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)

        async def run(author: Any) -> dict[str, Any]:
            try:
                commit = await caller.services.data_models.resolve_delete(
                    author, workspace_id, scope, name, branch=branch
                )
            except ModelNotFoundError:
                raise await unknown(caller, workspace_id, branch, scope, name) from None
            return {"deleted": f"{scope}/{name}", "commit": commit}

        return await caller.write("delete_schema", workspace_id, branch, f"{scope}/{name}", run)

    @server.tool(
        description=(
            "Le socle commun que le moteur valide EN PLUS du modèle qu'un TYPE D'EVENT"
            " désigne. À lire avant d'écrire un tel modèle : ces propriétés existent déjà"
            " dans tout payload, et les redéclarer est refusé (propriete_du_socle). Ce sont"
            " aussi les propriétés qu'une clé d'unicité peut nommer sans être dans le modèle."
            " Rendu en JSON SCHEMA, lu du moteur installé — avec les `format`, les"
            " descriptions et les obligatoires, qu'une liste de noms aurait perdus."
        )
    )
    async def get_event_base(ctx: Context[Any, Request]) -> dict[str, Any]:
        # Aucun workspace, aucune branche : la réponse ne dépend que du moteur installé.
        # Le portillon MCP s'applique quand même, c'est `caller_of` qui l'a déjà exigé.
        caller_of(ctx)
        return {"schema": socle_schema()}

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
