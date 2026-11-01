"""La LECTURE de ce que cette stack sert, pour son administrateur et pour le diagnostic.

Lecture seule, et c'est une décision : aucune route ne permet de choisir une version ici.
Le choix appartient à un humain chez l'enrôlement — autorité unique sur ce qu'un
environnement héberge —, et une route d'écriture, même réservée à l'administrateur de
cette stack, ferait exister deux sources pour la même décision.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from environnement.hosting.service import HostingService

router = APIRouter(prefix="/api/hosting")


class HostingStateOut(BaseModel):
    """Ce qui est ordonné, ce qui est servi EN BASE, et ce que l'arbre porte vraiment.

    Les trois, et séparément. `tree_commit` est lu dans git, `served_commit` est la trace
    qu'on a écrite : les deux peuvent diverger — un volume neuf après un redéploiement — et
    ne montrer que la trace cacherait précisément le cas qu'on cherche quand une stack ne
    se comporte pas comme sa version annoncée.
    """

    model_config = ConfigDict(extra="forbid")

    # Nuls ensemble : aucun ordre n'a jamais été reçu, et c'est l'état du premier jour.
    workspace_id: str | None
    ordered_number: int | None
    ordered_commit: str | None
    served_commit: str | None
    refusal: str | None
    tree_commit: str | None


@router.get("", response_model=HostingStateOut)
async def get_hosting_state(request: Request) -> HostingStateOut:
    """Ne lève jamais : « rien n'est hébergé » est un état, pas une erreur."""
    service: HostingService = request.app.state.hosting
    vue, tete = await service.resolve_hosted_version()
    if vue is None:
        return HostingStateOut(
            workspace_id=None,
            ordered_number=None,
            ordered_commit=None,
            served_commit=None,
            refusal=None,
            tree_commit=tete,
        )
    return HostingStateOut(
        workspace_id=vue.workspace_id,
        ordered_number=vue.ordered_number,
        ordered_commit=vue.ordered_commit,
        served_commit=vue.served_commit,
        refusal=vue.reason,
        tree_commit=tete,
    )
