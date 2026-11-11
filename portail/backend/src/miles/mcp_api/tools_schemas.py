"""Les schémas du paramétrage — modèles de données et événements de workflow.

UNE série de primitives pour les deux familles, le premier argument disant laquelle
(décision de Gael du 11/11/2026, voir `families.py`). Les règles propres à chaque famille
vivent dans les descriptions, parce que c'est là qu'un agent les lit.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from pydantic import Field
from starlette.requests import Request

from miles.mcp_api.calls import caller_of, tool_refusal
from miles.mcp_api.families import (
    EVENT,
    Kind,
    Name,
    ReadBranch,
    Scope,
    Workspace,
    WriteBranch,
    entry_out,
    family_of,
    unknown,
    written_out,
)
from miles.workflowevents.schema import socle_fields
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
            " Un MODÈLE se désigne par $ref: miles:/shared/<nom> ou"
            " miles:/domains/<domaine>/<nom> — depuis un modèle comme depuis un événement."
            " Pour un ÉVÉNEMENT, le schéma ne décrit que les données MÉTIER : le moteur"
            " valide en plus un socle commun (get_event_base), dont les propriétés ne se"
            " redéclarent pas, et `additionalProperties: false` est refusé parce qu'il"
            " rendrait tout payload réel invalide."
        )
    ),
]


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Liste les schémas d'une branche, avec leur emplacement. `kind` choisit la"
            " famille : les modèles de données, ou les événements de workflow."
        )
    )
    async def list_schemas(
        kind: Kind, workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, str]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        service = family_of(caller, kind).service
        try:
            entries = await service.resolve_list(caller.viewer, workspace_id, branch=branch)
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [entry_out(e) for e in entries]

    @server.tool(description="Lit un schéma : son emplacement et son YAML tel quel.")
    async def get_schema(
        kind: Kind,
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: ReadBranch = None,
    ) -> dict[str, str]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        chosen = family_of(caller, kind)
        try:
            entry, content = await chosen.service.resolve_get(
                caller.viewer, workspace_id, scope, name, branch=branch
            )
        except chosen.not_found:
            raise await unknown(caller, kind, workspace_id, branch, scope, name) from None
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return entry_out(entry) | {"content": content}

    @server.tool(
        description=(
            "Crée un schéma dans une branche enfant. Refus structurés : yaml_invalide,"
            " modele_non_conforme ou evenement_non_conforme selon `kind` (tous les écarts),"
            " nom_pris, domaine_inconnu (le domaine se crée d'abord par create_domain)."
        )
    )
    async def create_schema(
        kind: Kind,
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = family_of(caller, kind).service

        async def run(author: Any) -> dict[str, Any]:
            entry, commit = await service.resolve_create(
                author, workspace_id, scope, name, content, branch=branch
            )
            return written_out(entry, commit)

        return await caller.write(
            "create_schema", workspace_id, branch, f"{kind}:{scope}/{name}", run
        )

    @server.tool(
        description=(
            "Remplace le schéma ENTIER d'un élément existant, dans une branche enfant. Pour"
            " ne changer qu'une propriété, préférer set_schema_property : l'artefact est plus"
            " petit, et ce qu'il ne nomme pas ne peut pas disparaître. Le nom ne change pas :"
            " renommer, c'est créer puis supprimer. La version monte de 1, tenue par Miles."
        )
    )
    async def replace_schema(
        kind: Kind,
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        content: Content,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        chosen = family_of(caller, kind)

        async def run(author: Any) -> dict[str, Any]:
            try:
                entry, commit = await chosen.service.resolve_replace(
                    author, workspace_id, scope, name, content, branch=branch
                )
            except chosen.not_found:
                raise await unknown(caller, kind, workspace_id, branch, scope, name) from None
            return written_out(entry, commit)

        return await caller.write(
            "replace_schema", workspace_id, branch, f"{kind}:{scope}/{name}", run
        )

    @server.tool(
        description=(
            "Supprime un schéma d'une branche enfant. Un MODÈLE encore désigné est refusé"
            " (modele_utilise) : le refus nomme ce qui le désigne, un autre modèle ou un"
            " événement. Un ÉVÉNEMENT n'est désigné par rien du paramétrage ; c'est le"
            " script de workflow qui le déclare qui cessera de se charger."
        )
    )
    async def delete_schema(
        kind: Kind,
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        chosen = family_of(caller, kind)

        async def run(author: Any) -> dict[str, Any]:
            try:
                commit = await chosen.service.resolve_delete(
                    author, workspace_id, scope, name, branch=branch
                )
            except chosen.not_found:
                raise await unknown(caller, kind, workspace_id, branch, scope, name) from None
            return {"deleted": f"{kind}:{scope}/{name}", "commit": commit}

        return await caller.write(
            "delete_schema", workspace_id, branch, f"{kind}:{scope}/{name}", run
        )

    @server.tool(
        description=(
            "Le socle commun que le moteur valide EN PLUS du schéma d'un ÉVÉNEMENT. À lire"
            " avant d'en écrire un : ces propriétés existent déjà dans tout payload, et les"
            " redéclarer est refusé (propriete_du_socle). Lu du moteur installé, pas d'une"
            " liste tenue à la main. Un modèle de données n'a pas de socle."
        )
    )
    async def get_event_base(ctx: Context[Any, Request]) -> list[dict[str, Any]]:
        # Aucun workspace, aucune branche : la réponse ne dépend que du moteur installé.
        # Le portillon MCP s'applique quand même, c'est `caller_of` qui l'a déjà exigé.
        caller_of(ctx)
        return [
            {"name": nom, "type": type_declare, "read_only": lecture_seule, "kind": EVENT}
            for nom, type_declare, lecture_seule in socle_fields()
        ]

    @server.tool(
        description=(
            "Ajoute un domaine (répertoire domains/<nom>/) dans une branche enfant. Un schéma"
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
