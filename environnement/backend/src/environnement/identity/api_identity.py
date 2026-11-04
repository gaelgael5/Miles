from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from miles_socle.pairing.api_admin import pairing_error
from miles_socle.signing.peers import IdentityError

from environnement.identity.api_schemas import (
    AssignedEnvironmentViewOut,
    assigned_environment_out,
)
from environnement.identity.service import IdentityService

# La SEULE route d'administration que ce produit ajoute au demandeur générique. Les
# autres — identité, pair, demande, état de l'appariement — sont servies par le routeur du
# socle (`miles_socle.pairing.api_admin`), le même pour les deux demandeurs.
#
# Même préfixe que lui, et deux routeurs plutôt qu'un : le préfixe nomme ce que les routes
# servent, pas le fichier qui les porte. Les fondre obligerait le socle à connaître ce que
# ce produit tient en plus d'un pair.
router = APIRouter(prefix="/api/identity")


def _service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity
    return service


@router.get("/environment", response_model=AssignedEnvironmentViewOut)
async def get_assigned_environment(request: Request) -> AssignedEnvironmentViewOut | JSONResponse:
    """L'environnement du référentiel auquel le module d'enrôlement nous a rattachés.

    Route à part de l'état d'appariement, et non un champ de plus dans sa réponse : les
    deux émettent chacune leur appel signé vers le pair, et les fondre ferait échouer
    l'une avec l'autre. L'écran veut au contraire pouvoir dire « apparié, mais
    l'environnement n'a pas pu être rafraîchi ».

    Un appel SORTANT à chaque affichage, borné par `PEER_HTTP_TIMEOUT_S`. Le pair
    injoignable n'est pas une erreur ici : la réponse porte alors la dernière valeur
    connue et sa date, avec `fresh: false` — c'est le repli assumé du ticket 2edf1f3c.
    """
    try:
        vue = await _service(request).resolve_assigned_environment()
    except IdentityError as exc:
        # Pas de pair apparié : il n'y a personne à qui demander. 404 et non une vue vide,
        # qui se lirait « aucun environnement rattaché » alors qu'il n'y a pas
        # d'appariement du tout. Traduit par le socle, pour que le même refus ne rende
        # jamais deux codes différents selon la route qui l'a rencontré.
        return pairing_error(exc)
    return assigned_environment_out(vue)
