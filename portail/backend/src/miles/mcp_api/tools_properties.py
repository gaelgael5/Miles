"""Modifier UNE propriété d'un schéma, sans renvoyer le document entier.

Demandé par Gael le 11/11/2026, et la raison est écrite dans sa demande : « ça permettra
aux IA de générer de plus petits artefacts pour modifier les models ». Un agent qui
ajoutait un champ devait reproduire tout le schéma ; plus le modèle est riche, plus
l'artefact est gros, et plus il y a d'occasions de perdre en route ce qu'il ne voulait pas
toucher. Ici, ce que l'appel ne nomme pas ne peut pas disparaître.

Les deux familles, par le même premier argument que le reste de la surface.

**Pas de primitive séparée pour les renvois**, et c'est la consigne du même jour (« pas la
peine d'avoir des méthodes qui font la même chose en double ») : un renvoi EST une
propriété dont le schéma vaut `$ref: miles:/…`. `set_schema_property` l'ajoute et le
change donc déjà, avec la vérification que la cible existe et est visible.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.datamodels.grammar import load_yaml
from miles.datamodels.patch import PropertyPathError, remove_property, set_property
from miles.mcp_api.calls import caller_of
from miles.mcp_api.errors import refusal
from miles.mcp_api.families import (
    Kind,
    Name,
    Scope,
    Workspace,
    WriteBranch,
    family_of,
    unknown,
    written_out,
)

Path_ = Annotated[
    list[str],
    Field(
        description=(
            "Le chemin de la propriété, segment par segment depuis la racine du schéma :"
            ' ["Montant"] pour une propriété de premier niveau, ["adresse", "ville"]'
            ' pour une propriété imbriquée, ["lignes", "[]", "article"] pour une'
            " propriété des éléments d'un tableau. Une LISTE et non un chemin pointé : un"
            " nom de propriété JSON Schema peut contenir un point. Un `$ref` ne se traverse"
            " pas (refus renvoi_traverse) : modifiez le schéma qu'il désigne."
        )
    ),
]
PropertySchema = Annotated[
    str,
    Field(
        description=(
            "Le schéma de CETTE propriété, en YAML : « type: string » , « type: number »,"
            " « type: array\\nitems:\\n  type: string », ou un renvoi vers un modèle —"
            " « $ref: miles:/shared/personne ». C'est ainsi qu'on ajoute ou change un"
            " renvoi : il n'y a pas de primitive à part pour ça."
        )
    ),
]
Required = Annotated[
    bool | None,
    Field(
        description=(
            "true rend la propriété obligatoire, false la rend facultative, et OMIS ne touche"
            " pas à la liste des obligatoires — pour qu'une correction de type ne dégrade pas"
            " une obligation qu'on n'a pas nommée. Une propriété neuve naît facultative."
        )
    ),
]


def _path_refusal(exc: PropertyPathError) -> ToolError:
    return ToolError(refusal(exc.code, chemin=exc.where, existants=exc.existing))


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Pose ou remplace UNE propriété d'un schéma, dans une branche enfant — sans"
            " renvoyer le document. Le reste du schéma (autres propriétés, $defs, mots-clefs"
            " d'extension) est conservé tel quel. Le document complet est ensuite validé"
            " comme un remplacement entier : mêmes écarts, même version, même event."
            " Refus de chemin : propriete_inconnue, chemin_sans_proprietes,"
            " tableau_sans_items, renvoi_traverse — chacun nomme ce qui existe à cet endroit."
        )
    )
    async def set_schema_property(
        kind: Kind,
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        path: Path_,
        schema: PropertySchema,
        ctx: Context[Any, Request],
        required: Required = None,
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        chosen = family_of(caller, kind)
        # Lu AVANT tout accès au dépôt : un fragment illisible ne coûte aucun clone.
        fragment = load_yaml(schema)

        async def run(author: Any) -> dict[str, Any]:
            def apply(document: dict[str, Any]) -> dict[str, Any]:
                return set_property(document, path, fragment, required=required)

            try:
                entry, commit = await chosen.service.resolve_patch(
                    author, workspace_id, scope, name, apply, branch=branch
                )
            except chosen.not_found:
                raise await unknown(caller, kind, workspace_id, branch, scope, name) from None
            except PropertyPathError as exc:
                raise _path_refusal(exc) from None
            return written_out(entry, commit)

        element = f"{kind}:{scope}/{name}#{'.'.join(path)}"
        return await caller.write("set_schema_property", workspace_id, branch, element, run)

    @server.tool(
        description=(
            "Retire UNE propriété d'un schéma, dans une branche enfant, et son obligation"
            " avec elle — la laisser dans `required` ferait un schéma qu'aucun document ne"
            " peut satisfaire. Le reste du schéma est conservé tel quel."
        )
    )
    async def remove_schema_property(
        kind: Kind,
        workspace_id: Workspace,
        scope: Scope,
        name: Name,
        path: Path_,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        chosen = family_of(caller, kind)

        async def run(author: Any) -> dict[str, Any]:
            def apply(document: dict[str, Any]) -> dict[str, Any]:
                return remove_property(document, path)

            try:
                entry, commit = await chosen.service.resolve_patch(
                    author, workspace_id, scope, name, apply, branch=branch
                )
            except chosen.not_found:
                raise await unknown(caller, kind, workspace_id, branch, scope, name) from None
            except PropertyPathError as exc:
                raise _path_refusal(exc) from None
            return written_out(entry, commit)

        element = f"{kind}:{scope}/{name}#{'.'.join(path)}"
        return await caller.write("remove_schema_property", workspace_id, branch, element, run)
