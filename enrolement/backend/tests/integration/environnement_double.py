from __future__ import annotations

from dataclasses import dataclass, field

import httpx
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, sign_call
from miles_socle.signing.keys import KeyPair, generate_keypair, load_private_key
from miles_socle.signing.protocol import (
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PEER_PING_PATH,
    PING_BODY,
)


@dataclass
class EnvironmentDouble:
    """Contrepartie de test : le côté « module d'environnement » du protocole.

    C'est une doublure de l'AUTRE PRODUIT, jamais de notre code — le test de frontière
    interdit qu'un produit en importe un autre, et c'est bien ce qu'on veut : ce qui est
    éprouvé ici est le côté enrôlement, en entier et pour de vrai.

    Elle ne réimplémente aucune cryptographie : elle appelle `sign_call` du socle, celui-là
    même que l'environnement emploie. Une doublure qui forgerait ses signatures autrement
    prouverait seulement qu'on sait écrire une doublure, pas que les deux bouts s'accordent.
    """

    origin: str = "http://environnement.test"
    keypair: KeyPair = field(default_factory=generate_keypair)

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

    def knock_body(self) -> bytes:
        return b'{"public_key": "%s"}' % self.keypair.public_key.encode("ascii")


def confirm_body(code: str) -> bytes:
    return b'{"code": "%s"}' % code.encode("ascii")
