from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field
from starlette.requests import Request

from miles.accounts.layout import MODES, SERVED_MODES, Delivery
from miles.accounts.service import (
    AccountsService,
    DeliveryRefusedError,
    ReferenceState,
    StorageUnknownError,
)
from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.mcp_api.tools_models import ReadBranch, Workspace, WriteBranch

StorageName = Annotated[
    str,
    Field(description="Nom d'un storage de la branche : celui dont les objets sont les comptes."),
]
Mode = Annotated[
    str | None,
    Field(
        description=(
            "Mode d'envoi du code d'enregistrement : whatsapp, viber, signal, sms ou email."
            " SEUL `email` est servi pour l'instant ; les autres sont refusés. Omis avec"
            " `address_field` : l'envoi déclaré est EFFACÉ."
        )
    ),
]
AddressField = Annotated[
    str | None,
    Field(
        description=(
            "Jpath de la propriété du compte qui porte l'adresse d'envoi (« $.email »)."
            " Doit désigner une valeur du modèle que déclare le storage, jamais un objet"
            " ni un tableau. Va de pair avec `mode` : l'un sans l'autre est refusé."
        )
    ),
]


def _service(caller: Caller) -> AccountsService:
    service: AccountsService = caller.services.accounts
    return service


def _out(state: ReferenceState) -> dict[str, Any]:
    problem = state.problem
    return {
        "storage": None if state.reference is None else state.reference.storage,
        "model": state.model,
        "path": "comptes/reference.yaml",
        "delivery": None
        if state.reference is None or state.reference.delivery is None
        else {
            "mode": state.reference.delivery.mode,
            "address_field": state.reference.delivery.field,
        },
        "modes": list(MODES),
        "served_modes": list(SERVED_MODES),
        "problem": None
        if problem is None
        else {"path": problem.path, "code": problem.code, "detail": problem.detail},
    }


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "La référence de compte d'une branche : LE storage dont les objets sont les"
            " comptes associés aux devices, et le modèle que ce storage déclare. Le modèle"
            " est LU dans le storage, il n'est pas stocké avec la référence. `storage` à"
            " null veut dire qu'aucune référence n'est déclarée — ce n'est pas une erreur."
            " `delivery` à null veut dire que le stockage est désigné mais pas encore"
            " l'envoi : ce n'est pas une erreur non plus. `modes` donne les modes connus,"
            " `served_modes` ceux qui sont réellement servis."
            " `problem` non nul veut dire que le dépôt se contredit : fichier illisible, ou"
            " storage désigné qui a disparu de la branche. Le réglage est DÉCLARÉ et pas"
            " encore servi : rien n'interroge ce storage, et aucun code n'est envoyé."
        )
    )
    async def get_account_reference(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            state = await _service(caller).resolve_get(caller.viewer, workspace_id, branch=branch)
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return _out(state)

    @server.tool(
        description=(
            "Désigne le storage qui sert de référence de compte sur une branche enfant."
            " Une branche n'en a qu'UNE : appeler de nouveau remplace. Avec `mode` et"
            " `address_field`, déclare aussi par quel moyen et vers quel champ du compte"
            " part le code d'enregistrement ; les OMETTRE EFFACE l'envoi déclaré, comme"
            " save_chain remplace une chaîne entière. Réécrire à l'identique ne produit"
            " aucun commit et rend `unchanged` à vrai. Refus : storage_inconnu (nomme les"
            " storages qui existent), mode_non_servi (nomme ceux qui le sont),"
            " champ_inconnu, chemin_de_propriete_attendu, valeur_attendue,"
            " tableau_interdit, envoi_incomplet."
        )
    )
    async def set_account_reference(
        workspace_id: Workspace,
        storage: StorageName,
        ctx: Context[Any, Request],
        mode: Mode = None,
        address_field: AddressField = None,
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)
        if (mode is None) != (address_field is None):
            # Refusé AVANT toute écriture : un mode sans champ ne dit pas où envoyer, et
            # un champ sans mode ne dit pas comment. Ni l'un ni l'autre n'est un réglage.
            raise ToolError(refusal("envoi_incomplet", mode=mode, address_field=address_field))
        delivery = None if mode is None or address_field is None else Delivery(mode, address_field)

        async def run(author: Any) -> dict[str, Any]:
            try:
                saved = await service.resolve_save(
                    author, workspace_id, storage, delivery, branch=branch
                )
            except StorageUnknownError as exc:
                # Nommés ICI et pas seulement comptés : un agent corrige alors sans
                # rappeler list_storages pour deviner ce qu'il a mal écrit.
                raise ToolError(
                    refusal("storage_inconnu", storage=exc.storage, existants=exc.known)
                ) from None
            except DeliveryRefusedError as exc:
                raise ToolError(
                    refusal(
                        exc.problem.code,
                        detail=exc.problem.detail,
                        modes=exc.modes,
                        servis=exc.served,
                    )
                ) from None
            return _out(saved.state) | {"unchanged": saved.unchanged}

        return await caller.write("set_account_reference", workspace_id, branch, storage, run)

    @server.tool(
        description=(
            "Retire la référence de compte d'une branche enfant. Sur une branche qui n'en"
            " porte aucune : sans effet, `removed` à faux, aucun commit — un rejeu ne"
            " doit pas échouer."
        )
    )
    async def remove_account_reference(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: WriteBranch = None
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = _service(caller)

        async def run(author: Any) -> dict[str, Any]:
            return {"removed": await service.resolve_remove(author, workspace_id, branch=branch)}

        return await caller.write("remove_account_reference", workspace_id, branch, "", run)
