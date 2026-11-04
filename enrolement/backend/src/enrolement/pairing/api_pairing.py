from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from miles_socle.signing.identity_model import (
    IdentityInconsistentError,
    IdentityMissingError,
    IdentitySlugTakenError,
)
from miles_socle.signing.peers import MAX_BASE_URL_LENGTH, IdentityError, IdentityInputError
from miles_socle.signing.peers import validate_base_url as _validate_base_url

from enrolement.pairing.api_schemas import (
    CodeOut,
    ContactUrlIn,
    EnvironmentDesignationIn,
    IdentityOut,
    PeerOut,
    RequestOut,
    code_out,
    identity_out,
    peer_out,
    request_out,
)
from enrolement.pairing.model import (
    EnvironmentAlreadyPairedError,
    EnvironmentNotApplicableError,
    EnvironmentNotDesignatedError,
    EnvironmentUnknownError,
    PairingCarriesDevicesError,
    PairingChangedElsewhereError,
    PairingSettledError,
    PairingSpeciesMismatchError,
    ParametrageAlreadyPairedError,
    PeerNotFoundError,
    RequestNotFoundError,
)
from enrolement.pairing.service import PairingService

# Routes d'ADMINISTRATION : le portillon exige une session, et c'est pour cela qu'elles
# sont dans un routeur distinct de celui des pairs. Une seule de ces routes rend un
# secret d'usage — le code —, et aucune n'est atteignable sans humain authentifié.
router = APIRouter(prefix="/api/pairing")


def _service(request: Request) -> PairingService:
    service: PairingService = request.app.state.pairing
    return service


def _error(exc: IdentityError) -> JSONResponse:
    if isinstance(exc, IdentityInputError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": exc.field}
        )
    if isinstance(exc, EnvironmentNotDesignatedError):
        # 409 et non 403 : rien ne manque au droit de la personne, c'est l'état de la
        # demande qui l'empêche. Le détail NOMME la cause — un bouton grisé muet fait
        # chercher la panne du côté des clés ou du réseau (ticket bf2115cd, critère 1).
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "environnement_non_designe"}
        )
    if isinstance(exc, EnvironmentNotApplicableError):
        # 409 : le geste n'a pas de sens pour cette espèce, et rien ne manque au droit de
        # la personne. Le détail NOMME l'espèce en cause — un refus générique ferait
        # chercher du côté des droits une liste déroulante qui n'aurait pas dû s'afficher.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "espece_sans_environnement"},
        )
    if isinstance(exc, PairingSpeciesMismatchError):
        # 409 : le geste à faire est de révoquer l'appariement existant, pas de corriger
        # une saisie ni de réessayer. Nommé, parce qu'un refus générique sur le bouton
        # « afficher le code » ferait chercher du côté des clés ou de l'horloge.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "espece_deja_appariee_autrement"},
        )
    if isinstance(exc, ParametrageAlreadyPairedError):
        # Distinct d'« environnement pris » : là il suffit d'en choisir un autre, ici il
        # n'y a pas de second choix — il faut révoquer celui qui est apparié.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "module_de_parametrage_deja_apparie"},
        )
    if isinstance(exc, EnvironmentAlreadyPairedError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "environnement_apparie"}
        )
    if isinstance(exc, PairingCarriesDevicesError):
        # Un refus NOMMÉ, et non une erreur générique : le geste à faire est de déplacer
        # les devices, pas de corriger une saisie ni de réessayer. Le compte, lui, ne sort
        # pas — l'écran le lit de la liste des appariements, qui est sa source pour
        # l'afficher, et deux sources finiraient par se contredire.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "appariement_porte_des_devices"},
        )
    if isinstance(exc, PairingChangedElsewhereError):
        # Une COURSE, pas une règle : le remède est de relire la liste. Confondu avec
        # « cet appariement est conclu », il ferait croire le geste interdit.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "appariement_change_ailleurs"},
        )
    if isinstance(exc, PairingSettledError):
        # Distinct du précédent, parce que les deux appellent des gestes différents :
        # déplacer les devices, ou changer l'environnement de l'appariement plutôt que
        # celui de la demande. Les fondre ferait chercher du côté de la liste déroulante.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT, content={"detail": "appariement_conclu"}
        )
    if isinstance(exc, EnvironmentUnknownError):
        # 404 sur l'ENVIRONNEMENT, et le détail le dit : un « absent » générique se lirait
        # « la demande a disparu », qui appelle un tout autre geste.
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": "environnement_absent"}
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
        return identity_out(await _service(request).resolve_identity())
    except IdentityError as exc:
        return _error(exc)


@router.get("/requests", response_model=list[RequestOut])
async def get_requests(request: Request) -> list[RequestOut] | JSONResponse:
    """Les environnements qui demandent à se connecter. Les échues ont déjà disparu."""
    try:
        demandes = await _service(request).resolve_pending_requests()
    except IdentityError as exc:
        return _error(exc)
    return [request_out(demande) for demande in demandes]


@router.get("/code", response_model=CodeOut)
async def get_code(request: Request, base_url: str = BaseUrlQuery) -> CodeOut | JSONResponse:
    """Le code à recopier dans l'environnement. Recalculé à chaque appel, jamais stocké.

    L'écran le redemande au rythme de la fenêtre : il n'est ni imprimable ni
    téléchargeable, et une capture d'écran oubliée cesse de valoir quelque chose.
    """
    try:
        return code_out(await _service(request).resolve_request_code(_base_url(base_url)))
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


@router.put("/requests/environment", response_model=RequestOut)
async def put_request_environment(
    request: Request, body: EnvironmentDesignationIn, base_url: str = BaseUrlQuery
) -> RequestOut | JSONResponse:
    """Désigne l'environnement auquel l'appariement sera rattaché.

    Condition de l'acceptation, et non formalité qui la suit : révéler le code EST le
    geste d'acceptation, et sans environnement désigné le code n'est pas révélable. Libre
    de changer tant que l'appariement n'est pas conclu.
    """
    try:
        demande = await _service(request).resolve_designate_environment(
            request_author(request), _base_url(base_url), body.environment_id
        )
    except IdentityError as exc:
        return _error(exc)
    return request_out(demande)


@router.put("/peers/environment", response_model=PeerOut)
async def put_peer_environment(
    request: Request, body: EnvironmentDesignationIn, base_url: str = BaseUrlQuery
) -> PeerOut | JSONResponse:
    """Pose l'environnement d'un appariement conclu : rattachement ou déplacement.

    Un seul geste côté humain, deux faits côté journal selon ce qu'il y avait avant.
    Sans toucher aux clés ni refaire l'appariement. Le déplacement est ouvert tant que
    l'appariement ne porte AUCUN device : avec des devices il emporterait leur destination,
    et ce geste-là se compte et se confirme pour lui-même (409
    `appariement_porte_des_devices`).
    """
    try:
        pair = await _service(request).resolve_set_peer_environment(
            request_author(request), _base_url(base_url), body.environment_id
        )
    except IdentityError as exc:
        return _error(exc)
    return peer_out(pair)


@router.put("/peers/contact", response_model=PeerOut)
async def put_peer_contact(
    request: Request, body: ContactUrlIn, base_url: str = BaseUrlQuery
) -> PeerOut | JSONResponse:
    """Change l'adresse où l'on JOINT cette stack. Son identité, elle, ne change pas.

    Les deux sont distinctes et le resteront : l'identité vient de la stack et entre dans
    ce qu'on vérifie d'elle ; l'adresse de contact est à nous, n'entre dans aucune
    signature, et c'est la seule chose que ce module compose vers l'extérieur. Elle est
    saisie ICI plutôt que déclarée par la stack — laisser un tiers que personne n'a encore
    authentifié désigner la cible de nos appels sortants reviendrait à lui confier ce que
    nous composons.
    """
    try:
        pair = await _service(request).resolve_set_peer_contact_url(
            request_author(request), _base_url(base_url), body.contact_url
        )
    except IdentityError as exc:
        return _error(exc)
    return peer_out(pair)


@router.get("/peers", response_model=list[PeerOut])
async def get_peers(request: Request) -> list[PeerOut]:
    return [peer_out(pair) for pair in await _service(request).resolve_peers()]


@router.delete("/peers", status_code=status.HTTP_204_NO_CONTENT)
async def delete_peer(request: Request, base_url: str = BaseUrlQuery) -> Response:
    """Révoque l'appariement : la clé du pair est DÉTRUITE, et ses devices libérés.

    `DELETE` et non un drapeau sur une route de mise à jour, parce que c'est bien une
    destruction : l'appariement n'existe plus, et aucun appel signé de cette origine ne
    sera plus accepté. L'environnement, lui, reste au référentiel — révoquer porte sur
    l'appariement, pas sur l'environnement.

    La conséquence sur le parc — des devices remis en attente d'affectation — est montrée
    à l'humain par l'écran AVANT qu'il ne confirme ; cette route ne la rappelle pas, elle
    l'applique.
    """
    try:
        await _service(request).resolve_revoke_pairing(request_author(request), _base_url(base_url))
    except IdentityError as exc:
        return _error(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _base_url(raw: str) -> str:
    # Entrée utilisateur employée ensuite comme clé de base ET comme données associées du
    # chiffrement : validée avant tout usage, jamais concaténée sur la foi de la saisie.
    return _validate_base_url(raw)
