from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from miles_socle.signing.calls import (
    ORIGIN_HEADER,
    SIGNATURE_HEADER,
    CallSignatureError,
    sign_call,
    verify_call,
)
from miles_socle.signing.keys import (
    KeyPair,
    generate_keypair,
    load_private_key,
    parse_public_key,
)
from miles_socle.signing.protocol import (
    ENVIRONMENT_BODY,
    GIT_CONNECTIONS_PATH,
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PAIRING_REVOKED_PATH,
    PAIRING_STATUS_PATH,
    PEER_ENVIRONMENT_PATH,
    PEER_PING_PATH,
    PING_BODY,
)


@dataclass
class RequesterDouble:
    """Contrepartie de test : le côté DEMANDEUR du protocole, quelle qu'en soit l'espèce.

    C'est une doublure de l'AUTRE PRODUIT — module d'environnement ou module de
    paramétrage —, jamais de notre code : le test de frontière interdit qu'un produit en
    importe un autre, et c'est bien ce qu'on veut : ce qui est éprouvé ici est le côté
    enrôlement, en entier et pour de vrai.

    UNE doublure pour les deux espèces, et non deux : le côté demandeur est le même code
    depuis le 29/10/2026 (`miles_socle.pairing`), et deux doublures laisseraient croire
    qu'il y a deux protocoles.

    Elle ne réimplémente aucune cryptographie : elle appelle `sign_call` du socle, celui-là
    même que l'environnement emploie. Une doublure qui forgerait ses signatures autrement
    prouverait seulement qu'on sait écrire une doublure, pas que les deux bouts s'accordent.
    """

    origin: str = "http://environnement.test"
    keypair: KeyPair = field(default_factory=generate_keypair)
    # Nom déclaré. Valeur neutre par défaut ; les tests qui éprouvent l'échappement en
    # passent de hostiles.
    name: str = "Environnement de recette"
    # L'espèce déclarée en frappant. `None` ne la déclare PAS, et c'est un cas à éprouver
    # pour lui-même : un demandeur d'avant l'espèce doit continuer d'être lu comme un
    # environnement, sans quoi le champ ajouté au contrat aurait rompu ce qui marchait.
    species: str | None = None
    # La clé publique du module d'ENRÔLEMENT, telle que cette contrepartie la détient
    # après l'appariement. C'est contre elle qu'elle vérifie l'avis de révocation.
    expects_public_key: str = ""
    # Ce qu'elle a reçu, et de qui. Les tests y lisent ce qui est RÉELLEMENT arrivé plutôt
    # que de s'en remettre à l'intention du code appelant.
    revoked: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    dialled: list[str] = field(default_factory=list)

    def headers(self, path: str, body: bytes, *, method: str = "POST") -> dict[str, str]:
        entete = sign_call(
            load_private_key(self.keypair.private_pem),
            origin=self.origin,
            method=method,
            target=path,
            body=body,
        )
        return {
            ORIGIN_HEADER: self.origin,
            SIGNATURE_HEADER: entete,
            "Content-Type": "application/json",
        }

    async def post(self, client: httpx.AsyncClient, path: str, body: bytes) -> httpx.Response:
        return await client.post(path, content=body, headers=self.headers(path, body))

    async def knock(self, client: httpx.AsyncClient) -> httpx.Response:
        return await self.post(client, PAIRING_REQUEST_PATH, self.knock_body())

    async def confirm(self, client: httpx.AsyncClient, code: str) -> httpx.Response:
        return await self.post(client, PAIRING_CONFIRM_PATH, confirm_body(code))

    async def ping(self, client: httpx.AsyncClient) -> httpx.Response:
        return await self.post(client, PEER_PING_PATH, PING_BODY)

    async def status(self, client: httpx.AsyncClient) -> httpx.Response:
        return await self.post(client, PAIRING_STATUS_PATH, PING_BODY)

    async def environment(self, client: httpx.AsyncClient) -> httpx.Response:
        """Demande à quel environnement du référentiel cet appariement est rattaché."""
        return await self.post(client, PEER_ENVIRONMENT_PATH, ENVIRONMENT_BODY)

    async def confide(self, client: httpx.AsyncClient, body: bytes) -> httpx.Response:
        """Confie des connexions git. Rien ne distingue cet appel d'un autre pour la signature.

        La charge est COMPOSÉE ICI, et c'est une limite connue de cette campagne : elle
        éprouve le RÉCEPTEUR, et une faute dans la composition du module de paramétrage
        resterait invisible d'ici. C'est la campagne du portail qui l'éprouve, contre une
        contrepartie qui garde les corps reçus (leçon du 29/10/2026).
        """
        return await self.post(client, GIT_CONNECTIONS_PATH, body)

    def knock_body(self) -> bytes:
        # Construit à la main plutôt que par `json.dumps` : ce sont ces OCTETS-LÀ qui sont
        # signés, et un ré-encodage côté client produirait une autre suite d'octets donc
        # une signature refusée. Les valeurs sont échappées par `json.dumps` champ à champ.
        cle, nom = json.dumps(self.keypair.public_key), json.dumps(self.name)
        if self.species is None:
            return f'{{"public_key": {cle}, "name": {nom}}}'.encode()
        espece = json.dumps(self.species)
        return f'{{"public_key": {cle}, "name": {nom}, "species": {espece}}}'.encode()

    def app(self) -> FastAPI:
        """La contrepartie qui REÇOIT l'avis de révocation, et qui le vérifie vraiment.

        Elle appelle `verify_call` du socle contre la clé publique du module d'enrôlement,
        exactement comme le fera le vrai module d'environnement. Une doublure qui dirait
        « reçu » sans vérifier prouverait seulement qu'on sait écrire une doublure
        complaisante — et le ticket demande précisément qu'un avis non signé soit refusé.
        """
        app = FastAPI()

        @app.post(PAIRING_REVOKED_PATH, status_code=204)
        async def pairing_revoked(request: Request) -> Response:
            body = await request.body()
            origine = request.headers.get(ORIGIN_HEADER) or ""
            self.dialled.append(request.url.netloc)
            try:
                verify_call(
                    parse_public_key(self.expects_public_key),
                    request.headers.get(SIGNATURE_HEADER),
                    origin=origine,
                    method=request.method,
                    target=request.url.path,
                    body=body,
                )
            except CallSignatureError:
                self.refused.append(origine)
                return Response(status_code=401)
            self.revoked.append(origine)
            return Response(status_code=204)

        return app


def confirm_body(code: str) -> bytes:
    return b'{"code": "%s"}' % code.encode("ascii")


def connexion(
    identifiant: str,
    credential: str,
    *,
    label: str | None = None,
    base_url: str = "https://github.com/yoops",
    workspaces: Sequence[tuple[str, str | None]] = (),
) -> dict[str, Any]:
    """Une connexion git telle qu'un module de paramétrage la confie."""
    return {
        "id": identifiant,
        "label": label or f"Connexion {identifiant}",
        "base_url": base_url,
        "credential": credential,
        "workspaces": [{"id": w, "repo_url": r} for w, r in workspaces],
    }


def confide_body(revision: int, connections: Sequence[Mapping[str, Any]]) -> bytes:
    """L'état complet des connexions git, encodé pour la signature."""
    return json.dumps({"revision": revision, "connections": list(connections)}).encode("utf-8")
