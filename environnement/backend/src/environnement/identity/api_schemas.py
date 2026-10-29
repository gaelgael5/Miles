from __future__ import annotations

from datetime import datetime

from miles_socle.signing.identity_model import ModuleIdentity
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import MAX_BASE_URL_LENGTH, MAX_DECLARED_NAME_LENGTH
from miles_socle.signing.protocol import PongOut
from pydantic import BaseModel, ConfigDict, Field

from environnement.identity.model import EnrolmentPeer, PairingAttempt
from environnement.identity.peer_calls import PeerPong

# Les FORMES que les routes d'administration rendent, et la traduction du modèle vers
# elles. Séparées des routes parce qu'on les relit pour des raisons différentes : ici on
# vérifie ce qui SORT — et d'abord qu'aucune clé privée n'a de champ —, là-bas qui a le
# droit d'appeler.


class IdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # La clé PUBLIQUE sort, et c'est sa raison d'être : le module d'enrôlement en a besoin
    # pour vérifier nos appels. La clé privée n'a aucun champ ici, dans aucun sens.
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime


class PeerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(max_length=MAX_BASE_URL_LENGTH)
    public_key: str = Field(max_length=64)


class PairingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # L'origine du module d'enrôlement chez qui frapper. Saisie par un administrateur :
    # validée par le service avant tout usage en URL d'appel sortant.
    base_url: str = Field(max_length=MAX_BASE_URL_LENGTH)
    # Le nom sous lequel CE module se présentera. Il sert à ce qu'un humain, devant la
    # liste des demandes à l'autre bout, reconnaisse celle qu'il accepte — il n'identifie
    # rien, et deux environnements peuvent porter le même.
    #
    # Borne GROSSIÈRE, plus large que la règle : la vraie — 80 caractères, pas de
    # caractère de contrôle — est appliquée par le service, qui refuse en NOMMANT le
    # champ. Borner au plus juste ici ferait rendre le 422 générique de FastAPI, qui
    # n'apprend rien à qui doit corriger sa saisie.
    name: str = Field(max_length=MAX_DECLARED_NAME_LENGTH * 4)


class PairingConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Le code recopié depuis l'écran du module d'enrôlement. Borné ici, validé au chiffre
    # près par le service : six caractères suffisent à refuser une saisie démesurée avant
    # qu'elle n'atteigne quoi que ce soit.
    code: str = Field(max_length=16)


class AttemptOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    created_at: datetime
    name: str | None
    expires_at: datetime | None


class PairingStateOut(BaseModel):
    """L'état que l'écran rend lisible, et les deux moitiés qui le composent.

    La tentative et le pair voyagent ENSEMBLE : un ré-appariement les fait coexister, et
    un écran qui ne verrait que l'état remplacerait l'un par l'autre avant que l'humain
    n'ait tranché.
    """

    model_config = ConfigDict(extra="forbid")

    state: str
    attempt: AttemptOut | None
    peer: PeerOut | None


class PeerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    # Le nom que CE module a déclaré en s'appariant — pas celui du pair, qui n'en déclare
    # aucun. Il permet de retrouver son environnement dans la liste de l'autre bout.
    declared_name: str | None
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime
    updated_at: datetime


def identity_out(identity: ModuleIdentity) -> IdentityOut:
    return IdentityOut(
        public_key=identity.public_key,
        public_key_fingerprint=fingerprint(identity.public_key),
        algorithm=identity.algorithm,
        created_at=identity.created_at,
    )


def peer_out(peer: EnrolmentPeer) -> PeerOut:
    return PeerOut(
        base_url=peer.base_url,
        declared_name=peer.declared_name,
        public_key=peer.public_key,
        public_key_fingerprint=fingerprint(peer.public_key),
        algorithm=peer.algorithm,
        created_at=peer.created_at,
        updated_at=peer.updated_at,
    )


def pong_out(pong: PeerPong) -> PongOut:
    return PongOut(
        module=pong.module,
        origin=pong.origin,
        verified_key_fingerprint=pong.verified_key_fingerprint,
        own_key_fingerprint=pong.own_key_fingerprint,
    )


def attempt_out(attempt: PairingAttempt) -> AttemptOut:
    return AttemptOut(
        base_url=attempt.base_url,
        created_at=attempt.created_at,
        name=attempt.name,
        expires_at=attempt.expires_at,
    )
