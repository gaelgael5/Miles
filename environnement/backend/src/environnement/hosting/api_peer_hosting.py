"""La route par laquelle l'enrôlement ORDONNE de servir une version.

Authentifiée par SIGNATURE, et c'est la seule voie : ce module ne choisit pas sa version,
et il n'existe ici aucune route d'administration qui permettrait d'en choisir une. Le
geste appartient à un humain chez l'enrôlement, autorité unique — même règle que pour
l'environnement assigné.

Routeur à part de celui du socle : celui-là sert l'appariement, le même pour les deux
demandeurs, et l'hébergement n'est l'affaire que de cette espèce-ci. Ses chemins entrent
dans la liste blanche du portillon par DÉRIVATION, de sorte qu'un chemin ouvert à côté de
sa vérification ne soit pas exprimable.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from miles_socle.pairing.service import PairingRequesterService
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, CallSignatureError
from miles_socle.signing.hosting import HOSTED_VERSION_PATH, HostedVersionIn, HostedVersionOut
from miles_socle.signing.peers import IdentityError
from pydantic import ValidationError

from environnement.hosting.service import HostingService

router = APIRouter()


@router.post(HOSTED_VERSION_PATH, response_model=HostedVersionOut)
async def post_hosted_version(request: Request) -> HostedVersionOut | JSONResponse:
    """Sers cette version du workspace, et dis ce que tu sers.

    La signature est vérifiée AVANT toute lecture du corps, et contre la clé du module
    d'enrôlement apparié : c'est elle qui fait du commit porté par l'ordre le seul élément
    authentifié de tout l'échange — la réponse du relais, elle, n'est pas signée.

    La réponse porte l'ordre ET ce qui est servi, jamais l'un seul : « reçu » et « servi »
    sont deux faits distincts, et les confondre ferait afficher « à jour » chez
    l'enrôlement à une stack qui n'a rien appliqué.
    """
    service: HostingService = request.app.state.hosting
    pairing: PairingRequesterService = request.app.state.identity
    # Lu AVANT la vérification parce qu'il entre dans ce qui est signé ; pas interprété
    # pour autant — seule son empreinte sert à ce stade.
    body = await request.body()
    try:
        await pairing.resolve_verify_incoming(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=body,
        )
    except (CallSignatureError, IdentityError):
        # Un seul refus, quelle qu'en soit la raison : dire laquelle offrirait un oracle
        # pour approcher l'une par l'autre. La raison précise est au journal.
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "signature_refusee"}
        )
    try:
        ordre = HostedVersionIn.model_validate_json(body)
    except ValidationError:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "corps_invalide"},
        )
    return await service.resolve_order(ordre)
