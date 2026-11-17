"""Les types d'event de workflow : les DÉCLARATIONS de l'artefact d'un périmètre.

Elles n'ont pas de place dans `tools_schemas.py`, et c'est tout l'objet du renversement du
14/11/2026 : un type d'event n'est plus un document mais un `DEFINE EVENT … AS @modele` de
`shared/shared.wf` ou `domains/<d>/<d>.wf`. Le payload qu'il décrit est un modèle
ORDINAIRE, que `create_schema` écrit comme les autres. Deux surfaces, donc, et pas un
argument `kind` : ce qu'on écrit ici n'est pas un schéma, c'est un nom, un libellé, une
désignation de modèle et des clés d'anti-doublon.

Un agent qui ajoute un type d'event fait deux gestes : `create_schema` pour le modèle de
son payload, puis `declare_event_type`. L'ordre compte — la déclaration refuse un modèle
absent (`declaration_non_conforme`, `modele_inconnu`) — et les descriptions le disent,
parce qu'un agent qui l'ignore enchaîne deux refus avant de le deviner.

Pas de `get_event_type` : `list_event_types` rend TOUT d'une déclaration (libellé, modèle,
clés, modèle manquant). Une lecture unitaire n'aurait rien ajouté qu'un aller-retour, là
où un schéma, lui, porte un contenu que la liste ne peut pas rendre.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.mcp_api.tool_args import ReadBranch, Workspace, WriteBranch
from miles.workflowevents.dsl import fragment_path
from miles.workflowevents.reading import DeclaredType
from miles.workflowevents.service import EventTypeNotFoundError, WorkflowEventsService

Scope = Annotated[
    str,
    Field(
        description=(
            "Périmètre de la déclaration : « shared » pour un type transverse, sinon le nom"
            " d'un domaine existant (list_domains). Un domaine dont le nom porte un tiret"
            " existe légitimement mais ne peut pas porter de type d'event : le DSL du moteur"
            " ne sait pas écrire `@domains.mon-domaine.…` (refus champ_invalide,"
            " scope_non_ecrivable)."
        )
    ),
]
Name = Annotated[
    str,
    Field(
        description=(
            "Nom du type d'event, tel qu'un script de workflow l'écrira : minuscules,"
            " chiffres et soulignés, 63 caractères au plus, SANS TIRET — le DSL du moteur le"
            " refuserait. Unique dans tout le workspace, et pas seulement dans le périmètre :"
            " un script qui inclut deux artefacts déclarant le même nom ne charge pas du tout"
            " (refus nom_pris_ailleurs)."
        )
    ),
]
Label = Annotated[str, Field(description="Libellé affiché, sur une ligne ; jamais vide.")]
# Le modèle se désigne par le COUPLE que prend `get_schema`, et non par une URI
# `miles:/shared/colis` comme dans les étapes d'une chaîne. La raison : on écrit ici à
# côté des primitives de schéma, et un agent qui vient de créer le modèle a déjà ces deux
# valeurs en main. Les chaînes gardent l'URI parce que c'est elle qui est dans le dépôt.
ModelScope = Annotated[
    str,
    Field(description="Portée du modèle qui décrit le payload : « shared » ou un domaine."),
]
ModelName = Annotated[str, Field(description="Nom de ce modèle (voir list_schemas).")]
Unique = Annotated[
    list[str],
    Field(
        description=(
            "Clés de l'anti-doublon, DANS L'ORDRE : le moteur en dérive un hash par"
            " concaténation, donc réordonner la liste invalide la reconnaissance de tous les"
            " doublons passés. Chaque clé nomme une propriété du modèle ou du socle commun"
            " (get_event_base) ; une autre est refusée. Liste vide : aucun anti-doublon."
        )
    ),
]


def _service(caller: Caller) -> WorkflowEventsService:
    return caller.services.workflow_events


def _out(declared: DeclaredType) -> dict[str, Any]:
    return {
        "scope": declared.scope,
        "name": declared.name,
        "label": declared.label,
        # L'artefact qui PORTE la déclaration, et le modèle qu'elle désigne : deux fichiers
        # du dépôt, nommés comme partout ailleurs sur cette surface par leur chemin.
        "path": fragment_path(declared.scope),
        "model": declared.model_path,
        "model_scope": declared.model[0],
        "model_name": declared.model[1],
        "unique": list(declared.unique),
        # Rendu, jamais caché : une déclaration dont le modèle manque est ce qui bloquera
        # l'enregistrement d'une version, et un agent qui ne le voit pas cherche ailleurs.
        "model_missing": declared.model_missing,
    }


async def _unknown(caller: Caller, workspace_id: str, branch: str | None, name: str) -> ToolError:
    """Le refus « inconnu », avec ce qui existe : l'agent se corrige sans explorer."""
    declared = await _service(caller).resolve_list(caller.viewer, workspace_id, branch=branch)
    return ToolError(
        refusal(
            "evenement_inconnu",
            evenement=name,
            existants=[f"{d.scope}/{d.name}" for d in declared],
        )
    )


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Liste les types d'event de workflow d'une branche : ce que les `DEFINE EVENT`"
            " des artefacts de périmètre déclarent. `path` est l'artefact qui porte la"
            " déclaration, `model` le modèle du payload. model_missing : le modèle désigné"
            " manque sur la branche, ce qui empêchera d'enregistrer une version."
        )
    )
    async def list_event_types(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, Any]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            declared = await _service(caller).resolve_list(
                caller.viewer, workspace_id, branch=branch
            )
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [_out(d) for d in declared]

    @server.tool(
        description=(
            "Déclare un type d'event dans l'artefact de son périmètre, sur une branche"
            " enfant. Le modèle du payload doit DÉJÀ exister (create_schema d'abord) : il"
            " décrit les seules données métier, le moteur validant en plus un socle commun"
            " (get_event_base). Refus : nom_pris, nom_pris_ailleurs, domaine_inconnu,"
            " portee_du_modele (un périmètre transverse ne désigne pas un modèle de"
            " domaine), declaration_non_conforme (modèle absent, fermé, qui redéclare une"
            " propriété du socle, ou clé d'unicité qui ne désigne rien). Rejeu à l'identique :"
            " sans effet, unchanged vaut true."
        )
    )
    async def declare_event_type(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        label: Label,
        model_scope: ModelScope,
        model_name: ModelName,
        ctx: Context[Any, Request],
        unique: Unique | None = None,
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            declared, commit = await service.resolve_declare(
                author,
                workspace_id,
                scope,
                label,
                name,
                (model_scope, model_name),
                unique or [],
                branch=branch,
            )
            return _out(declared) | {"commit": commit, "unchanged": commit is None}

        return await caller.write(
            "declare_event_type", workspace_id, branch, f"{scope}/{name}", run
        )

    @server.tool(
        description=(
            "Change le libellé, le modèle du payload ou les clés d'unicité d'un type déjà"
            " déclaré. Le NOM ne change pas : c'est lui qu'un script de workflow écrit, et le"
            " renommer casserait tout `ON EVENT` qui le nomme — renommer, c'est déclarer"
            " l'autre nom puis supprimer celui-ci. Les clés omises sont EFFACÉES : cet appel"
            " remplace la déclaration entière."
        )
    )
    async def replace_event_type(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        label: Label,
        model_scope: ModelScope,
        model_name: ModelName,
        ctx: Context[Any, Request],
        unique: Unique | None = None,
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                declared, commit = await service.resolve_replace(
                    author,
                    workspace_id,
                    scope,
                    name,
                    label,
                    (model_scope, model_name),
                    unique or [],
                    branch=branch,
                )
            except EventTypeNotFoundError:
                raise await _unknown(caller, workspace_id, branch, f"{scope}/{name}") from None
            return _out(declared) | {"commit": commit, "unchanged": commit is None}

        return await caller.write(
            "replace_event_type", workspace_id, branch, f"{scope}/{name}", run
        )

    @server.tool(
        description=(
            "Supprime une déclaration de type d'event d'une branche enfant. Le modèle de son"
            " payload RESTE : c'est un modèle comme un autre, et delete_schema le supprime"
            " séparément. Supprimer le dernier type d'un périmètre retire son artefact, qui"
            " serait une erreur de syntaxe s'il restait vide."
        )
    )
    async def delete_event_type(
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                commit = await service.resolve_delete(
                    author, workspace_id, scope, name, branch=branch
                )
            except EventTypeNotFoundError:
                raise await _unknown(caller, workspace_id, branch, f"{scope}/{name}") from None
            return {"deleted": f"{scope}/{name}", "commit": commit}

        return await caller.write("delete_event_type", workspace_id, branch, f"{scope}/{name}", run)
