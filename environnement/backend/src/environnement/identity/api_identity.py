from __future__ import annotations

from datetime import datetime

import httpx
import structlog
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from miles_socle.signing.keys import fingerprint
from pydantic import BaseModel, ConfigDict, Field

# Le contrat de l'échange est défini là où ce module le SERT : une seconde définition
# de même forme, ici, aurait divergé au premier champ ajouté d'un seul côté.
from environnement.identity.api_peer import PongOut
from environnement.identity.model import (
    MAX_BASE_URL_LENGTH,
    EnrolmentPeer,
    IdentityError,
    IdentityInconsistentError,
    IdentityInputError,
    IdentityMissingError,
    IdentitySlugTakenError,
    ModuleIdentity,
    OriginMissingError,
    PeerMissingError,
    PeerRefusedError,
    PeerUnexpectedResponseError,
)
from environnement.identity.service import IdentityService, PeerPong

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/identity")


class IdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # La clé PUBLIQUE sort, et c'est sa raison d'être : le module d'enrôlement en a besoin
    # pour vérifier nos appels. La clé privée n'a aucun champ ici, dans aucun sens.
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime


class PeerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(max_length=MAX_BASE_URL_LENGTH)
    public_key: str = Field(max_length=64)


class PeerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime
    updated_at: datetime


def _service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity
    return service


def _identity_out(identity: ModuleIdentity) -> IdentityOut:
    return IdentityOut(
        public_key=identity.public_key,
        public_key_fingerprint=fingerprint(identity.public_key),
        algorithm=identity.algorithm,
        created_at=identity.created_at,
    )


def _peer_out(peer: EnrolmentPeer) -> PeerOut:
    return PeerOut(
        base_url=peer.base_url,
        public_key=peer.public_key,
        public_key_fingerprint=fingerprint(peer.public_key),
        algorithm=peer.algorithm,
        created_at=peer.created_at,
        updated_at=peer.updated_at,
    )


def _pong_out(pong: PeerPong) -> PongOut:
    return PongOut(
        module=pong.module,
        origin=pong.origin,
        verified_key_fingerprint=pong.verified_key_fingerprint,
        own_key_fingerprint=pong.own_key_fingerprint,
    )


def _error(exc: IdentityError) -> JSONResponse:
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
        return _identity_out(await _service(request).resolve_identity())
    except IdentityError as exc:
        return _error(exc)


@router.get("/peer", response_model=PeerOut)
async def get_peer(request: Request) -> PeerOut | JSONResponse:
    try:
        return _peer_out(await _service(request).resolve_peer())
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
            request_author(request), body.base_url, body.public_key
        )
    except IdentityError as exc:
        return _error(exc)
    return _peer_out(peer)


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
    return _pong_out(pong)
