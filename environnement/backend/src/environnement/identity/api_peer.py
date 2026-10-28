from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, CallSignatureError
from miles_socle.signing.keys import fingerprint
from pydantic import BaseModel, ConfigDict

from environnement.identity.model import IdentityError
from environnement.identity.service import PEER_PING_PATH, IdentityService

MODULE = "environnement"
# Routeur à part, et c'est tout l'intérêt : `app.py` lit SES chemins pour les déclarer au
# portillon d'authentification. Le chemin ouvert et la route qui vérifie la signature
# viennent ainsi de la même déclaration — un chemin ouvert sans sa vérification n'est plus
# exprimable. Même raison que la table des écrans du front, pour la même panne : ce qui
# est tenu à deux endroits finit par diverger, et la divergence paraît verte.
router = APIRouter()


class PongOut(BaseModel):
    """Réponse de l'échange de vivacité. UNE seule définition, pour les deux sens.

    Ce module la sert sur sa propre route, et l'attend de son pair quand c'est lui qui
    appelle : c'est le MÊME contrat. Deux modèles de même forme auraient divergé au
    premier champ ajouté d'un seul côté.
    """

    model_config = ConfigDict(extra="forbid")

    module: str
    # NOTRE adresse publique, pas celle de l'appelant — qui la connaît déjà. Nulle quand
    # MILES_PUBLIC_URL n'est pas configurée ; dans ce cas ce module ne peut pas non plus
    # signer d'appel sortant, et le dire est plus utile que de rendre une chaîne vide.
    origin: str | None
    # Empreinte de la clé qui a VÉRIFIÉ l'appel, et empreinte de la nôtre. C'est ce qui
    # rend un désaccord de clés diagnosticable après un ré-appariement : l'appelant
    # compare ce qu'il croit détenir à ce que nous avons réellement employé.
    verified_key_fingerprint: str
    own_key_fingerprint: str


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
    service: IdentityService = request.app.state.identity
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
        module=MODULE,
        origin=service.origin,
        verified_key_fingerprint=fingerprint(peer.public_key),
        own_key_fingerprint=fingerprint(identity.public_key),
    )
