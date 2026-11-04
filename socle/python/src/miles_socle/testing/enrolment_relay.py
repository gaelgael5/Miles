"""Le RELAIS de contenu de la contrepartie d'enrôlement : servir un bundle à qui l'ordonne.

Fichier à part de `enrolment_double.py`, qui est à sa limite de 300 lignes, et la coupure
suit une frontière réelle : là-bas on double l'APPARIEMENT, ici on sert du contenu de
dépôt — la seule route du protocole dont la réponse n'est pas du JSON.

Cette doublure ne fabrique AUCUN bundle : les tests lui en donnent, fabriqués avec un vrai
git. Le socle ne lance pas git, et une doublure qui en fabriquerait un prouverait seulement
qu'on sait écrire une doublure — alors que ce qu'on éprouve, c'est que le destinataire
VÉRIFIE le commit avant de poser l'arbre.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from miles_socle.signing.hosting import HOSTING_BUNDLE_PATH, HostingBundleIn

BUNDLE_MEDIA_TYPE = "application/octet-stream"


class SignatureChecker(Protocol):
    """Ce qu'il faut de la contrepartie : savoir vérifier. Rien de son appariement."""

    bundles: dict[str, bytes]
    bundle_requests: list[HostingBundleIn]
    expects_public_key: str

    def _verifie(self, request: Request, body: bytes, public_key: str) -> bool: ...


def mount_hosting_relay(app: FastAPI, double: SignatureChecker) -> None:
    """Pose la route du relais sur l'application de la contrepartie."""

    @app.post(HOSTING_BUNDLE_PATH)
    async def hosting_bundle(request: Request) -> Response:
        body = await request.body()
        # Vérifiée comme la vraie route le fait, et contre la même clé : sans cela la
        # doublure laisserait passer ce que le vrai relais refuse, et le demandeur
        # paraîtrait savoir signer alors qu'il ne le saurait pas.
        if not double._verifie(request, body, double.expects_public_key):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "signature_refusee"},
            )
        demande = HostingBundleIn.model_validate_json(body)
        double.bundle_requests.append(demande)
        paquet = double.bundles.get(demande.commit)
        if paquet is None:
            # Le vrai relais refuse en 403 ce qui n'est pas ordonné, sans détail. La
            # doublure rend le même code : un demandeur qui traiterait 404 et 403
            # différemment passerait les tests et échouerait en face.
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "contenu_non_ordonne"},
            )
        return Response(content=paquet, media_type=BUNDLE_MEDIA_TYPE)
