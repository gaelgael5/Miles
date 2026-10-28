from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from miles_socle.signing.calls import (
    ORIGIN_HEADER,
    SIGNATURE_HEADER,
    CallSignatureError,
    verify_call,
)
from miles_socle.signing.keys import KeyPair, fingerprint, generate_keypair, parse_public_key

PEER_ORIGIN = "http://enrolement.test"


@dataclass
class EnrolmentDouble:
    """Contrepartie de test : le côté « module d'enrôlement » de l'échange signé.

    C'est une doublure de l'AUTRE PRODUIT, pas de notre code. Son côté du protocole
    s'écrira avec le ticket 6a0daab6 ; ce qui existe aujourd'hui, c'est le vérificateur du
    socle — celui-là même qu'il emploiera. La doublure ne réimplémente donc aucune
    cryptographie : elle se contente d'appeler `verify_call`, et c'est ce qui donne sa
    valeur au test. Une doublure qui dirait « oui » sans vérifier prouverait seulement
    qu'on sait écrire une doublure complaisante.
    """

    keypair: KeyPair = field(default_factory=generate_keypair)
    # La clé publique que la contrepartie détient POUR NOUS. Une autre valeur simule un
    # appariement rompu : elle doit alors refuser nos appels.
    expects_public_key: str = ""
    received: list[str] = field(default_factory=list)

    def app(self) -> FastAPI:
        app = FastAPI()

        @app.post("/api/peer/ping")
        async def ping(request: Request) -> JSONResponse:
            body = await request.body()
            origine = request.headers.get(ORIGIN_HEADER) or ""
            try:
                verify_call(
                    parse_public_key(self.expects_public_key),
                    request.headers.get(SIGNATURE_HEADER),
                    origin=origine,
                    method=request.method,
                    target=request.url.path,
                    body=body,
                )
            except CallSignatureError as refus:
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": refus.reason}
                )
            self.received.append(origine)
            return JSONResponse(
                content={
                    "module": "enrolement",
                    "origin": PEER_ORIGIN,
                    "verified_key_fingerprint": fingerprint(self.expects_public_key),
                    "own_key_fingerprint": fingerprint(self.keypair.public_key),
                }
            )

        return app
