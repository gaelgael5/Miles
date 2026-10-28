from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from miles_socle.signing.identity_model import (
    IdentityInconsistentError,
    IdentityMissingError,
    IdentitySlugTakenError,
    ModuleIdentity,
)
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import MAX_BASE_URL_LENGTH, IdentityError, IdentityInputError
from miles_socle.signing.peers import validate_base_url as _validate_base_url
from pydantic import BaseModel, ConfigDict

from enrolement.pairing.model import (
    EnvironmentPeer,
    PairingCode,
    PairingRequest,
    PeerNotFoundError,
    RequestNotFoundError,
)
from enrolement.pairing.service import PairingService

# Routes d'ADMINISTRATION : le portillon exige une session, et c'est pour cela qu'elles
# sont dans un routeur distinct de celui des pairs. Une seule de ces routes rend un
# secret d'usage — le code —, et aucune n'est atteignable sans humain authentifié.
router = APIRouter(prefix="/api/pairing")


class IdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # La clé PUBLIQUE sort, et c'est sa raison d'être : les environnements appariés en ont
    # besoin pour vérifier nos appels. La clé privée n'a aucun champ ici.
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime


class RequestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    # Texte libre venu d'un tiers que personne n'a encore authentifié. Il aide un humain à
    # reconnaître la demande qu'il accepte, et n'identifie RIEN : deux demandes peuvent
    # porter le même, seule l'URL les distingue. Nul si la demande est antérieure au nom
    # déclaré. React l'échappe à l'affichage ; il n'est ni un identifiant ni une clef.
    name: str | None
    # L'empreinte, et non la clé : c'est elle qu'un humain compare à ce que l'écran de
    # l'environnement affiche, avant d'accepter.
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime
    expires_at: datetime


class CodeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    code: str
    # De quoi afficher le temps restant : sans lui, l'humain ne sait pas s'il lui reste
    # vingt-neuf secondes ou une, et colle un code périmé dont le refus ressemble à un
    # code faux.
    seconds_remaining: int


class PeerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    name: str | None
    # Nombre de devices que ce module a affectés à cet environnement. Il rend la
    # révocation décidable : révoquer un environnement qui porte des devices n'est pas le
    # même geste que révoquer un environnement vide (ticket ce66f5bb).
    #
    # NUL aujourd'hui, et c'est un refus de mentir : le référentiel des devices n'existe
    # pas encore (ticket de dispatch). Écrire 0 afficherait « aucun device » sur un écran
    # qui ne sait pas compter, et personne ne distinguerait plus « vide » d'« ignoré ».
    # Le champ existe pour que l'écran dise « — » dès maintenant, et la vérité ensuite.
    device_count: int | None
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime
    updated_at: datetime


def _service(request: Request) -> PairingService:
    service: PairingService = request.app.state.pairing
    return service


def _request_out(demande: PairingRequest) -> RequestOut:
    return RequestOut(
        base_url=demande.base_url,
        name=demande.name,
        public_key_fingerprint=fingerprint(demande.public_key),
        algorithm=demande.algorithm,
        created_at=demande.created_at,
        expires_at=demande.expires_at,
    )


def _peer_out(pair: EnvironmentPeer) -> PeerOut:
    return PeerOut(
        base_url=pair.base_url,
        name=pair.name,
        device_count=None,
        public_key=pair.public_key,
        public_key_fingerprint=fingerprint(pair.public_key),
        algorithm=pair.algorithm,
        created_at=pair.created_at,
        updated_at=pair.updated_at,
    )


def _code_out(code: PairingCode) -> CodeOut:
    return CodeOut(base_url=code.base_url, code=code.code, seconds_remaining=code.seconds_remaining)


def _identity_out(identity: ModuleIdentity) -> IdentityOut:
    return IdentityOut(
        public_key=identity.public_key,
        public_key_fingerprint=fingerprint(identity.public_key),
        algorithm=identity.algorithm,
        created_at=identity.created_at,
    )


def _error(exc: IdentityError) -> JSONResponse:
    if isinstance(exc, IdentityInputError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": exc.field}
        )
    if isinstance(exc, RequestNotFoundError | PeerNotFoundError):
        # 404 et non refus opaque : la personne est authentifiée et regarde son propre
        # écran. Lui cacher qu'une demande vient d'expirer ne protège de rien et
        # l'empêcherait de comprendre pourquoi la ligne a disparu.
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": "absent"})
    if isinstance(exc, IdentityMissingError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": "identite_absente"}
        )
    if isinstance(exc, IdentitySlugTakenError):
        # 503, comme l'incohérence : le module marche, c'est l'état de ses données qui
        # l'empêche d'avoir une identité, et le remède est une intervention, pas un correctif.
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "slug_de_l_identite_pris"},
        )
    if isinstance(exc, IdentityInconsistentError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "identite_incoherente"},
        )
    raise exc


BaseUrlQuery = Query(max_length=MAX_BASE_URL_LENGTH)


@router.get("/identity", response_model=IdentityOut)
async def get_identity(request: Request) -> IdentityOut | JSONResponse:
    try:
        return _identity_out(await _service(request).resolve_identity())
    except IdentityError as exc:
        return _error(exc)


@router.get("/requests", response_model=list[RequestOut])
async def get_requests(request: Request) -> list[RequestOut] | JSONResponse:
    """Les environnements qui demandent à se connecter. Les échues ont déjà disparu."""
    try:
        demandes = await _service(request).resolve_pending_requests()
    except IdentityError as exc:
        return _error(exc)
    return [_request_out(demande) for demande in demandes]


@router.get("/code", response_model=CodeOut)
async def get_code(request: Request, base_url: str = BaseUrlQuery) -> CodeOut | JSONResponse:
    """Le code à recopier dans l'environnement. Recalculé à chaque appel, jamais stocké.

    L'écran le redemande au rythme de la fenêtre : il n'est ni imprimable ni
    téléchargeable, et une capture d'écran oubliée cesse de valoir quelque chose.
    """
    try:
        return _code_out(await _service(request).resolve_request_code(_base_url(base_url)))
    except IdentityError as exc:
        return _error(exc)


@router.delete("/requests", status_code=status.HTTP_204_NO_CONTENT)
async def delete_request(request: Request, base_url: str = BaseUrlQuery) -> Response:
    """Refus humain : la demande disparaît et son secret avec elle.

    Annotée `Response` et non `None` : une route en 204 ne peut pas déclarer de corps, et
    un type de retour optionnel en fait déduire un à FastAPI — qui refuse de démarrer.
    """
    try:
        await _service(request).resolve_reject_request(request_author(request), _base_url(base_url))
    except IdentityError as exc:
        return _error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/peers", response_model=list[PeerOut])
async def get_peers(request: Request) -> list[PeerOut]:
    return [_peer_out(pair) for pair in await _service(request).resolve_peers()]


def _base_url(raw: str) -> str:
    # Entrée utilisateur employée ensuite comme clé de base ET comme données associées du
    # chiffrement : validée avant tout usage, jamais concaténée sur la foi de la saisie.
    return _validate_base_url(raw)
