from __future__ import annotations

import json
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
from miles_socle.signing.protocol import (
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PAIRING_STATUS_PATH,
    PEER_PING_PATH,
)

PEER_ORIGIN = "http://enrolement.test"
# Le code que cette contrepartie attend. Figé, parce que ce qui est éprouvé ici est le
# côté ENVIRONNEMENT : la dérivation TOTP, sa fenêtre et sa brûlure appartiennent au
# module d'enrôlement et sont éprouvées dans sa campagne, contre son vrai code.
EXPECTED_CODE = "314159"


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
    # Ce que la contrepartie répondra à la confirmation. Les refus du vrai module
    # d'enrôlement sont OPAQUES (401) sauf la dérive d'horloge (409), et c'est ce que ce
    # module doit savoir traduire sans rien inventer de ce que le pair n'a pas dit.
    confirm_status: int = 200
    confirm_payload: dict[str, object] | None = None
    # L'état que la contrepartie annoncera, et l'échéance qu'elle a accusée. C'est sur
    # ces deux-là que l'environnement tranche entre « refusée » et « expirée » : le pair
    # ne dit que « en attente » ou « inconnue », jamais laquelle des deux.
    #
    # Trois valeurs, et la troisième est celle du VRAI module d'enrôlement une fois la
    # demande disparue : il n'a plus aucune clé pour vérifier l'appel, et il refuse
    # plutôt que de confirmer à un inconnu qu'une origine n'est pas appariée.
    #   « en_attente » → 200 en attente | « inconnue » → 200 inconnue | « disparue » → 401
    status_state: str = "en_attente"
    expires_at: str = "2099-01-01T00:00:00+00:00"
    # Le nom déclaré tel qu'il est ARRIVÉ. Les tests y lisent ce qui est réellement parti,
    # plutôt que ce que l'écran croit avoir envoyé.
    received_names: list[str] = field(default_factory=list)
    # Les corps reçus, en OCTETS : c'est là-dedans qu'un test va chercher qu'aucune clé
    # privée n'est partie, plutôt que de s'en remettre à l'intention.
    bodies: list[bytes] = field(default_factory=list)

    def app(self) -> FastAPI:
        app = FastAPI()

        @app.post(PAIRING_REQUEST_PATH, status_code=202)
        async def pairing_request(request: Request) -> JSONResponse:
            body = await request.body()
            self.bodies.append(body)
            origine = request.headers.get(ORIGIN_HEADER) or ""
            # Le vrai module d'enrôlement vérifie la signature contre la clé que CE corps
            # dépose : la doublure fait de même, sans quoi elle laisserait passer ce que
            # le vrai refuserait.
            depose = str(json.loads(body)["public_key"])
            if not self._verifie(request, body, depose):
                return JSONResponse(status_code=401, content={"detail": "appariement_refuse"})
            self.expects_public_key = depose
            self.received.append(origine)
            self.received_names.append(str(json.loads(body)["name"]))
            return JSONResponse(
                status_code=202, content={"base_url": origine, "expires_at": self.expires_at}
            )

        @app.post(PAIRING_CONFIRM_PATH)
        async def pairing_confirm(request: Request) -> JSONResponse:
            body = await request.body()
            self.bodies.append(body)
            if not self._verifie(request, body, self.expects_public_key):
                return JSONResponse(status_code=401, content={"detail": "appariement_refuse"})
            if self.confirm_status != 200:
                return JSONResponse(
                    status_code=self.confirm_status,
                    content=self.confirm_payload or {"detail": "appariement_refuse"},
                )
            if str(json.loads(body)["code"]) != EXPECTED_CODE:
                return JSONResponse(status_code=401, content={"detail": "appariement_refuse"})
            return JSONResponse(
                content={
                    "base_url": PEER_ORIGIN,
                    "public_key": self.keypair.public_key,
                    "algorithm": "ed25519",
                }
            )

        @app.post(PAIRING_STATUS_PATH)
        async def pairing_status(request: Request) -> JSONResponse:
            body = await request.body()
            if not self._verifie(request, body, self.expects_public_key):
                return JSONResponse(status_code=401, content={"detail": "appariement_refuse"})
            if self.status_state == "disparue":
                return JSONResponse(status_code=401, content={"detail": "appariement_refuse"})
            if self.status_state != "en_attente":
                return JSONResponse(content={"state": "inconnue", "expires_at": None})
            return JSONResponse(content={"state": "en_attente", "expires_at": self.expires_at})

        @app.post(PEER_PING_PATH)
        async def ping(request: Request) -> JSONResponse:
            body = await request.body()
            origine = request.headers.get(ORIGIN_HEADER) or ""
            if not self._verifie(request, body, self.expects_public_key):
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "signature_refusee"},
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

    def _verifie(self, request: Request, body: bytes, public_key: str) -> bool:
        """La doublure ne réimplémente aucune cryptographie : elle appelle le socle.

        C'est ce qui donne sa valeur au test — une doublure qui dirait « oui » sans
        vérifier prouverait seulement qu'on sait écrire une doublure complaisante.
        """
        try:
            verify_call(
                parse_public_key(public_key),
                request.headers.get(SIGNATURE_HEADER),
                origin=request.headers.get(ORIGIN_HEADER) or "",
                method=request.method,
                target=request.url.path,
                body=body,
            )
        except (CallSignatureError, ValueError):
            return False
        return True
