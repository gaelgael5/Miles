from __future__ import annotations

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse

from miles_socle.pairing.service import PairingRequesterService
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, CallSignatureError
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import IdentityError
from miles_socle.signing.protocol import PAIRING_REVOKED_PATH, PEER_PING_PATH, PongOut

# Le service du demandeur est posé par le produit sous `app.state.identity`, et les deux
# le posent sous ce nom-là. C'est la convention de ce socle, et elle est écrite ici parce
# que c'est le seul endroit où elle est LUE : un produit qui la changerait verrait ses
# routes de pair tomber au premier appel, sans que rien d'autre ne bouge.
#
# Routeur à part, et c'est tout l'intérêt : `app.py` lit SES chemins pour les déclarer au
# portillon d'authentification. Le chemin ouvert et la route qui vérifie la signature
# viennent ainsi de la même déclaration — un chemin ouvert sans sa vérification n'est plus
# exprimable. Même raison que la table des écrans du front, pour la même panne : ce qui
# est tenu à deux endroits finit par diverger, et la divergence paraît verte.
router = APIRouter()


@router.post(PEER_PING_PATH, response_model=PongOut)
async def post_peer_ping(request: Request) -> PongOut | JSONResponse:
    """Échange de vivacité entre modules appariés, authentifié par SIGNATURE.

    Seule route de ce produit qui n'exige pas de session : elle est appelée de machine à
    machine, sans humain et sans cookie. C'est donc ici, et nulle part ailleurs, que
    l'autorisation se joue — la signature est vérifiée AVANT toute autre lecture.

    POST et non GET bien que l'échange ne modifie rien : une réponse de GET est cachable
    par n'importe quel intermédiaire, et une réponse servie d'un cache dirait que
    l'appariement est vivant alors qu'il ne l'est plus.
    """
    service: PairingRequesterService = request.app.state.identity
    # Le corps est lu AVANT la vérification parce qu'il entre dans ce qui est signé.
    # Il n'est pas interprété pour autant : seule son empreinte est employée ici.
    body = await request.body()
    try:
        peer = await service.resolve_verify_incoming(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=body,
        )
        identity = await service.resolve_identity()
    except (CallSignatureError, IdentityError):
        # Un seul refus, quelle qu'en soit la raison : dire laquelle offrirait un oracle
        # pour approcher l'une par l'autre. La raison précise est au journal, écrite par
        # le service, avec l'origine déclarée.
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "signature_refusee"}
        )
    return PongOut(
        # Le nom que CE produit se donne. Porté par le service plutôt que figé ici : ce
        # fichier sert les deux demandeurs, et un nom en dur y ferait répondre
        # « environnement » au module de paramétrage.
        module=service.module_name,
        origin=service.origin,
        verified_key_fingerprint=fingerprint(peer.public_key),
        own_key_fingerprint=fingerprint(identity.public_key),
    )


@router.post(PAIRING_REVOKED_PATH, status_code=status.HTTP_204_NO_CONTENT)
async def post_pairing_revoked(request: Request) -> Response:
    """Le module d'enrôlement nous dit qu'il vient de nous révoquer l'accès.

    SEULE route du protocole que ce module SERT et que l'enrôlement APPELLE : le sens
    inverse de toutes les autres. Elle existe parce que la révocation détruit chez lui
    notre clé publique — il ne peut donc plus vérifier que c'est bien nous qui demandons,
    et nous répondre « tu es révoqué » l'apprendrait à n'importe quel inconnu déclarant
    notre origine. Poussé, l'avis est signé de SA clé, que nous détenons encore.

    Vérifiée exactement comme l'échange de vivacité, et pas autrement : sans cela,
    n'importe qui ferait croire à cette stack qu'elle est révoquée, et son administrateur
    referait un appariement qui n'avait rien perdu.

    204 : rien à rendre. Ce que l'avis change est chez nous, et l'appelant n'en attend
    aucune donnée — il ne doit surtout pas attendre non plus que nous soyons debout.
    """
    service: PairingRequesterService = request.app.state.identity
    # Lu AVANT la vérification parce qu'il entre dans ce qui est signé ; jamais interprété.
    body = await request.body()
    try:
        await service.resolve_verify_incoming(
            declared_origin=request.headers.get(ORIGIN_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
            method=request.method,
            target=request.url.path,
            body=body,
        )
    except (CallSignatureError, IdentityError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "signature_refusee"}
        )
    await service.resolve_record_revocation()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
