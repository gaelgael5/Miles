from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from miles_socle.signing.identity_model import (
    IdentityInconsistentError,
    IdentityMissingError,
    IdentitySlugTakenError,
    OriginMissingError,
)
from miles_socle.signing.peers import (
    IdentityError,
    IdentityInputError,
)

# Le contrat de l'échange est au socle : ce module le SERT sur sa route de pair et
# l'ATTEND de son pair quand c'est lui qui appelle. Deux définitions de même forme
# auraient divergé au premier champ ajouté d'un seul côté.
from miles_socle.signing.protocol import PongOut

from environnement.identity.api_schemas import (
    AssignedEnvironmentViewOut,
    AttemptOut,
    IdentityOut,
    PairingConfirmIn,
    PairingIn,
    PairingStateOut,
    PeerIn,
    PeerOut,
    assigned_environment_out,
    attempt_out,
    identity_out,
    peer_out,
    pong_out,
)
from environnement.identity.model import (
    PairingAttemptMissingError,
    PairingRefusedByPeerError,
    PeerClockSkewError,
    PeerMissingError,
    PeerRefusedError,
    PeerUnexpectedResponseError,
)
from environnement.identity.service import IdentityService

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/identity")


def _service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity
    return service


def _error(exc: IdentityError) -> JSONResponse:
    if isinstance(exc, PeerClockSkewError):
        # Le seul refus d'appariement qui dise sa cause, et il la tient du pair. Sans lui,
        # on chercherait du côté du code pendant que la cause est une machine à l'heure près.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "horloges_desynchronisees", "drift_s": exc.drift_s},
        )
    if isinstance(exc, PairingRefusedByPeerError):
        # 409 : rien n'est à corriger dans la requête, c'est l'appariement qui n'a pas
        # abouti. Le pair ne dit pas lequel des cas, et ce module n'en invente pas un.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "appariement_refuse"}
        )
    if isinstance(exc, PairingAttemptMissingError):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": "aucune_demande"}
        )
    if isinstance(exc, IdentityInputError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": exc.field}
        )
    if isinstance(exc, IdentityMissingError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": "identite_absente"}
        )
    if isinstance(exc, PeerMissingError):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "aucun_pair"})
    if isinstance(exc, PeerUnexpectedResponseError):
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "reponse_inattendue_du_pair", "peer_status": exc.status_code},
        )
    if isinstance(exc, PeerRefusedError):
        # 409 : rien n'est à corriger dans la requête, c'est l'état de l'appariement qui
        # est en conflit — la clé que le pair détient pour nous n'est pas la nôtre.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "refuse_par_le_pair"}
        )
    if isinstance(exc, OriginMissingError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": "origine_absente"}
        )
    if isinstance(exc, IdentitySlugTakenError):
        # 503, comme l'incohérence : le module marche, c'est l'état de ses données qui
        # l'empêche d'avoir une identité, et le remède est une intervention, pas un correctif.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "slug_de_l_identite_pris"},
        )
    if isinstance(exc, IdentityInconsistentError):
        # 503 et non 500 : le module fonctionne, c'est son identité qui est inutilisable,
        # et le remède est une intervention sur les données, pas un correctif de code.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "identite_incoherente"},
        )
    raise exc


@router.get("", response_model=IdentityOut)
async def get_identity(request: Request) -> IdentityOut | JSONResponse:
    try:
        return identity_out(await _service(request).resolve_identity())
    except IdentityError as exc:
        return _error(exc)


@router.get("/peer", response_model=PeerOut)
async def get_peer(request: Request) -> PeerOut | JSONResponse:
    try:
        return peer_out(await _service(request).resolve_peer())
    except IdentityError as exc:
        return _error(exc)


@router.put("/peer", response_model=PeerOut)
async def put_peer(request: Request, body: PeerIn) -> PeerOut | JSONResponse:
    """Déclare le module d'enrôlement apparié, en attendant le protocole d'appariement.

    Remplace celui qui existe, jamais un second : le modèle n'admet qu'un pair, et un
    doublon silencieux laisserait deux identités pour une stack. L'opération est donc
    idempotente, et c'est un PUT.
    """
    try:
        peer = await _service(request).resolve_register_peer(
            request_author(request),
            body.base_url,
            body.public_key,
            # Sans adresse de contact, le pair est joignable là où il se nomme : c'est le
            # cas ordinaire, et le dire ici une fois vaut mieux qu'un défaut calculé plus
            # bas, où l'oubli d'un appelant deviendrait invisible.
            body.contact_url or body.base_url,
        )
    except IdentityError as exc:
        return _error(exc)
    return peer_out(peer)


@router.post("/peer/ping", response_model=PongOut)
async def post_peer_ping(request: Request) -> PongOut | JSONResponse:
    """Émet un appel SIGNÉ vers le pair et rend sa réponse : l'autre sens de l'échange.

    Déclenchée par un administrateur, cette route ne porte aucune décision : elle sert à
    constater qu'un appel signé part, qu'il est accepté, et que les deux modules parlent
    bien de la même paire de clés — ce qu'aucun contrôle de santé local ne peut dire.
    """
    try:
        pong = await _service(request).resolve_ping_peer()
    except IdentityError as exc:
        return _error(exc)
    except httpx.HTTPError as exc:
        # L'injoignabilité du pair n'est pas une faute de ce module : 502, et le détail
        # va au journal, jamais dans la réponse — il porte des URL et des messages de
        # bibliothèque dont l'appelant n'a pas à connaître la forme.
        log.warning("ping_du_pair_en_echec", error=type(exc).__name__)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": "pair_injoignable"}
        )
    return pong_out(pong)


def _injoignable(exc: httpx.HTTPError) -> JSONResponse:
    """L'injoignabilité du pair n'est pas une faute de ce module.

    Le détail va au journal, jamais dans la réponse : il porte des URL et des messages de
    bibliothèque dont l'appelant n'a pas à connaître la forme.
    """
    log.warning("pair_injoignable", error=type(exc).__name__)
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY, content={"detail": "pair_injoignable"}
    )


@router.get("/pairing", response_model=AttemptOut)
async def get_pairing(request: Request) -> AttemptOut | JSONResponse:
    """La demande d'appariement en cours : chez qui on a frappé, et quand."""
    try:
        return attempt_out(await _service(request).resolve_attempt())
    except IdentityError as exc:
        return _error(exc)


@router.get("/pairing/state", response_model=PairingStateOut)
async def get_pairing_state(request: Request) -> PairingStateOut | JSONResponse:
    """L'état complet, celui que l'écran interroge en boucle pendant l'attente.

    C'est la seule route qui sait dire « refusée » : la confirmation, elle, rend le même
    refus opaque pour un code faux et pour une demande disparue — volontairement, à
    l'autre bout. Sans cette route, l'écran afficherait « en attente » pour toujours.
    """
    try:
        etat = await _service(request).resolve_pairing_state()
    except IdentityError as exc:
        return _error(exc)
    return PairingStateOut(
        state=etat.state,
        attempt=None if etat.attempt is None else attempt_out(etat.attempt),
        peer=None if etat.peer is None else peer_out(etat.peer),
    )


@router.get("/environment", response_model=AssignedEnvironmentViewOut)
async def get_assigned_environment(request: Request) -> AssignedEnvironmentViewOut | JSONResponse:
    """L'environnement du référentiel auquel le module d'enrôlement nous a rattachés.

    Route à part de l'état d'appariement, et non un champ de plus dans sa réponse : les
    deux émettent chacune leur appel signé vers le pair, et les fondre ferait échouer
    l'une avec l'autre. L'écran veut au contraire pouvoir dire « apparié, mais
    l'environnement n'a pas pu être rafraîchi ».

    Un appel SORTANT à chaque affichage, borné par `PEER_HTTP_TIMEOUT_S`. Le pair
    injoignable n'est pas une erreur ici : la réponse porte alors la dernière valeur
    connue et sa date, avec `fresh: false` — c'est le repli assumé du ticket.
    """
    try:
        vue = await _service(request).resolve_assigned_environment()
    except IdentityError as exc:
        # Pas de pair apparié : il n'y a personne à qui demander. 404 et non une vue vide,
        # qui se lirait « aucun environnement rattaché » alors qu'il n'y a pas
        # d'appariement du tout.
        return _error(exc)
    return assigned_environment_out(vue)


@router.post("/pairing", response_model=AttemptOut, status_code=status.HTTP_202_ACCEPTED)
async def post_pairing(request: Request, body: PairingIn) -> AttemptOut | JSONResponse:
    """Frappe chez un module d'enrôlement. 202 : rien n'est acquis sans un geste humain.

    Le geste suivant appartient à un administrateur de l'AUTRE module, qui voit la demande
    apparaître et en lit le code. C'est pour cela que cette route ne rend pas de pair.
    """
    try:
        attempt = await _service(request).resolve_request_pairing(
            request_author(request), body.base_url, body.name
        )
    except IdentityError as exc:
        return _error(exc)
    except httpx.HTTPError as exc:
        return _injoignable(exc)
    return attempt_out(attempt)


@router.post("/pairing/confirm", response_model=PeerOut)
async def post_pairing_confirm(request: Request, body: PairingConfirmIn) -> PeerOut | JSONResponse:
    """Présente le code recopié. À l'issue, chacun détient la clé publique de l'autre."""
    try:
        peer = await _service(request).resolve_confirm_pairing(request_author(request), body.code)
    except IdentityError as exc:
        return _error(exc)
    except httpx.HTTPError as exc:
        return _injoignable(exc)
    return peer_out(peer)


@router.delete("/pairing", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pairing(request: Request) -> Response:
    """Abandonne la demande en cours. Celle du pair expirera d'elle-même.

    Annotée `Response` et non `None` : une route en 204 ne peut pas déclarer de corps, et
    un type de retour optionnel en fait déduire un à FastAPI — qui refuse de démarrer.
    """
    try:
        await _service(request).resolve_cancel_attempt(request_author(request))
    except IdentityError as exc:
        return _error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
