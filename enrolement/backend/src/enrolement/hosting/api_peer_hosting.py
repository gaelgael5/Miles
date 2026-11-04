"""La route du RELAIS : servir à un environnement apparié le contenu de sa version.

Authentifiée par SIGNATURE, comme les autres routes de pair, et le portillon ne la laisse
passer que parce qu'elle l'est — sa déclaration est dérivée de ce routeur, de sorte qu'un
chemin ouvert à côté de sa vérification ne soit pas exprimable.

Routeur à part du routeur de pair de l'appariement : celui-là est à sa limite de 300
lignes, et la coupure suit une vraie frontière — là-bas on apparie, ici on sert du contenu.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, CallSignatureError
from miles_socle.signing.hosting import HOSTING_BUNDLE_PATH, HostingBundleIn
from miles_socle.signing.peers import IdentityError
from pydantic import ValidationError

from enrolement.hosting.gitcache import BundleTooLargeError
from enrolement.hosting.model import BundleRefusedError, HostingError
from enrolement.hosting.relay import HostingRelay
from enrolement.pairing.service import PairingService

log = structlog.get_logger(__name__)
router = APIRouter()
# Un bundle n'est pas du JSON et ne doit pas être interprété comme tel par un
# intermédiaire : type opaque, et aucun cache possible sur une réponse de POST.
BUNDLE_MEDIA_TYPE = "application/octet-stream"


@router.post(HOSTING_BUNDLE_PATH)
async def post_hosting_bundle(request: Request) -> Response:
    """Le contenu de la version ordonnée à l'environnement qui appelle.

    POST et non GET bien que rien ne soit modifié, pour deux raisons : la demande porte un
    corps qui entre dans la chaîne signée, et une réponse de GET est cachable par
    n'importe quel intermédiaire — un paramétrage servi d'un cache serait exactement la
    panne qu'on ne saurait pas diagnostiquer.

    L'ordre des vérifications n'est pas négociable : la SIGNATURE d'abord, avant toute
    lecture du corps, puis l'autorisation — être apparié ne donne droit qu'à SON workspace,
    à la version qu'on lui a ordonnée.
    """
    pairing: PairingService = request.app.state.pairing
    relay: HostingRelay = request.app.state.hosting_relay
    # Lu AVANT la vérification parce qu'il entre dans ce qui est signé ; pas interprété
    # pour autant — seule son empreinte sert ici.
    body = await request.body()
    try:
        pair = await pairing.resolve_verify_incoming(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=body,
        )
    except (CallSignatureError, IdentityError):
        # Un seul refus, quelle qu'en soit la raison : dire laquelle offrirait un oracle
        # pour approcher l'une par l'autre. La raison précise est au journal.
        return _refus(status.HTTP_401_UNAUTHORIZED, "signature_refusee")
    try:
        demande = HostingBundleIn.model_validate_json(body)
    except ValidationError:
        return _refus(status.HTTP_422_UNPROCESSABLE_CONTENT, "corps_invalide")
    try:
        paquet = await relay.resolve_bundle(pair.base_url, demande)
    except BundleRefusedError:
        # 403 et non 404 : la route existe et l'appelant est authentifié, c'est ce qu'il
        # demande qui lui est refusé. Sans détail — lui dire laquelle des conditions pèche
        # lui apprendrait l'état de notre référentiel.
        return _refus(status.HTTP_403_FORBIDDEN, "contenu_non_ordonne")
    except BundleTooLargeError:
        return _refus(status.HTTP_409_CONFLICT, "bundle_trop_volumineux")
    except HostingError:
        # Le dépôt ne se lit pas, ou le workspace n'est plus confié. Sans détail pour
        # l'appelant : la cause est chez nous, et c'est à notre administrateur qu'elle est
        # montrée — l'écran de l'enrôlement la nomme.
        log.warning("bundle_non_servi", peer_base_url=pair.base_url)
        return _refus(status.HTTP_409_CONFLICT, "relais_indisponible")
    return Response(content=paquet, media_type=BUNDLE_MEDIA_TYPE)


def _refus(code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})
