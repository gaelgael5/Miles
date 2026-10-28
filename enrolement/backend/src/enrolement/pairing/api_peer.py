from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER
from miles_socle.signing.identity_model import (
    IdentityInconsistentError,
    IdentitySlugTakenError,
)
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import IdentityError, IdentityInputError
from miles_socle.signing.protocol import (
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PAIRING_STATUS_PATH,
    PEER_PING_PATH,
    PairingConfirmIn,
    PairingConfirmOut,
    PairingRequestIn,
    PairingRequestOut,
    PairingStatusOut,
    PongOut,
)
from pydantic import BaseModel, ValidationError

from enrolement.pairing.model import (
    EnvironmentAlreadyPairedError,
    EnvironmentNotDesignatedError,
    PairingClockSkewError,
    PairingRefusedError,
)
from enrolement.pairing.service import PairingService

log = structlog.get_logger(__name__)
MODULE = "enrolement"
# Routeur à part, et c'est tout l'intérêt : `app.py` lit SES chemins pour les déclarer au
# portillon d'authentification. Le chemin ouvert et la route qui vérifie la signature
# viennent ainsi de la même déclaration — un chemin ouvert sans sa vérification n'est plus
# exprimable. Les trois routes d'ici sont authentifiées par signature, chacune contre une
# clé d'une provenance différente, et aucune n'est ouverte à un appel nu.
router = APIRouter()


def _service(request: Request) -> PairingService:
    service: PairingService = request.app.state.pairing
    return service


def _refus(exc: IdentityError) -> JSONResponse:
    """La réponse d'un refus. UN seul code pour tous les cas d'appariement impossible.

    Dire lequel — demande inconnue, expirée, code faux, signature qui ne correspond pas —
    offrirait un oracle pour approcher l'un par l'autre. La raison précise est au journal,
    écrite par le service, avec l'origine déclarée.
    """
    if isinstance(exc, PairingClockSkewError):
        # L'exception à la règle, et elle n'ouvre rien : pour l'atteindre il faut avoir
        # passé la vérification de signature ET présenté un code dérivé du bon secret.
        # Qui la voit possède déjà tout ce que la distinction pourrait apprendre, et sans
        # elle on cherche du côté du code pendant que la cause est une horloge.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "horloges_desynchronisees", "drift_s": exc.drift_s},
        )
    if isinstance(exc, EnvironmentAlreadyPairedError):
        # Même exception à la règle, et pour la même raison que l'horloge : on ne
        # l'atteint qu'après avoir passé la vérification de signature ET présenté un code
        # dérivé du bon secret. Rien n'est révélé de plus que ce que l'appelant détient
        # déjà — et sans ce mot, l'exploitant retaperait des codes pendant que la cause
        # est chez nous : un autre appariement a pris l'environnement qu'on lui destinait.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "environnement_indisponible"},
        )
    if isinstance(exc, EnvironmentNotDesignatedError):
        # Ne devrait jamais se produire : le code n'est pas révélable sans environnement
        # désigné, et l'appelant n'a pu l'obtenir qu'une fois celui-ci choisi. Si cela
        # arrive, répondre « refusé » enverrait le diagnostic vers les clés ou l'horloge
        # alors que l'état est chez nous.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "environnement_non_designe"},
        )
    if isinstance(exc, IdentityInputError):
        # La clé mal formée est celle de l'APPELANT : lui en cacher la cause ne protège
        # personne et lui ferait chercher une panne de signature.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": exc.field}
        )
    if isinstance(exc, IdentitySlugTakenError | IdentityInconsistentError):
        # 503 : ce module marche, c'est l'état de SES données qui l'empêche d'avoir une
        # identité utilisable. Rien à corriger chez l'appelant, qui doit pouvoir le voir.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "identite_indisponible"},
        )
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "appariement_refuse"}
    )


def _parse[T: BaseModel](model: type[T], raw: bytes) -> T:
    return model.model_validate_json(raw)


def _corps_invalide() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": "corps_invalide"}
    )


@router.post(PAIRING_REQUEST_PATH, response_model=PairingRequestOut, status_code=202)
async def post_pairing_request(request: Request) -> PairingRequestOut | JSONResponse:
    """Un environnement frappe et dépose sa clé publique. 202 : rien n'est acquis.

    Le corps est lu en OCTETS avant d'être interprété, parce que c'est son empreinte qui
    entre dans la chaîne signée : l'interpréter puis le ré-encoder donnerait une autre
    suite d'octets, et la signature serait refusée à tort.

    La signature est vérifiée contre la clé que ce corps dépose. Elle n'authentifie donc
    PAS l'appelant — c'est l'humain qui le fera, avec le code — mais elle prouve qu'il
    détient la clé privée de la clé qu'il dépose. Sans elle, n'importe qui déposerait la
    clé d'un autre pour une origine qu'il ne contrôle pas.
    """
    raw = await request.body()
    try:
        corps = _parse(PairingRequestIn, raw)
    except ValidationError:
        return _corps_invalide()
    try:
        demande = await _service(request).resolve_open_request(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=raw,
            public_key=corps.public_key,
            name=corps.name,
        )
    except IdentityError as exc:
        return _refus(exc)
    return PairingRequestOut(base_url=demande.base_url, expires_at=demande.expires_at.isoformat())


@router.post(PAIRING_CONFIRM_PATH, response_model=PairingConfirmOut)
async def post_pairing_confirm(request: Request) -> PairingConfirmOut | JSONResponse:
    """Le code recopié est présenté : l'appariement se conclut, et notre clé part en retour."""
    raw = await request.body()
    try:
        corps = _parse(PairingConfirmIn, raw)
    except ValidationError:
        return _corps_invalide()
    try:
        conclu = await _service(request).resolve_confirm_pairing(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=raw,
            code=corps.code,
        )
    except IdentityError as exc:
        return _refus(exc)
    return PairingConfirmOut(
        base_url=conclu.base_url, public_key=conclu.public_key, algorithm=conclu.algorithm
    )


@router.post(PAIRING_STATUS_PATH, response_model=PairingStatusOut)
async def post_pairing_status(request: Request) -> PairingStatusOut | JSONResponse:
    """Où en est la demande de l'appelant. Signée : chacun ne peut lire que la sienne.

    Sans cette route, un écran d'environnement afficherait « en attente » pour toujours :
    son code refusé et sa demande disparue rendent le même refus opaque, volontairement,
    et rien ne lui dirait qu'un humain a dit non.
    """
    raw = await request.body()
    try:
        demande = await _service(request).resolve_request_state(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=raw,
        )
    except IdentityError as exc:
        return _refus(exc)
    if demande is None:
        return PairingStatusOut(state="inconnue", expires_at=None)
    return PairingStatusOut(state="en_attente", expires_at=demande.expires_at.isoformat())


@router.post(PEER_PING_PATH, response_model=PongOut)
async def post_peer_ping(request: Request) -> PongOut | JSONResponse:
    """Échange de vivacité avec un environnement apparié, authentifié par SIGNATURE.

    POST et non GET bien que l'échange ne modifie rien : une réponse de GET est cachable
    par n'importe quel intermédiaire, et une réponse servie d'un cache dirait que
    l'appariement est vivant alors qu'il ne l'est plus.
    """
    service = _service(request)
    # Lu AVANT la vérification parce qu'il entre dans ce qui est signé. Il n'est pas
    # interprété pour autant : seule son empreinte est employée ici.
    raw = await request.body()
    try:
        pair = await service.resolve_verify_incoming(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=raw,
        )
        identite = await service.resolve_identity()
    except PairingRefusedError:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "signature_refusee"}
        )
    except IdentityError as exc:
        return _refus(exc)
    return PongOut(
        module=MODULE,
        origin=service.origin,
        verified_key_fingerprint=fingerprint(pair.public_key),
        own_key_fingerprint=fingerprint(identite.public_key),
    )
