from __future__ import annotations

from datetime import datetime

from miles_socle.signing.identity_model import ModuleIdentity
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import MAX_BASE_URL_LENGTH, MAX_DECLARED_NAME_LENGTH
from miles_socle.signing.protocol import PongOut
from pydantic import BaseModel, ConfigDict, Field

from environnement.identity.model import (
    AssignedEnvironmentView,
    EnrolmentPeer,
    PairingAttempt,
)
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
    # L'adresse où JOINDRE le pair, quand elle diffère de l'origine qu'il déclare. Absente,
    # les deux valent `base_url` : celui qui n'en donne qu'une dit que son pair est
    # joignable là où il se nomme, et c'est le cas ordinaire.
    contact_url: str | None = Field(default=None, max_length=MAX_BASE_URL_LENGTH)


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
    # L'adresse où on le joint. Égale à `base_url` tant qu'aucun intermédiaire ne
    # s'interpose : l'écran ne la montre alors pas, deux lignes identiques faisant
    # chercher une différence qui n'existe pas.
    contact_url: str
    # Quand l'avis de révocation a été REÇU, nul tant qu'il n'est pas venu. Il n'est pas
    # cru sur parole : l'écran ne nomme la révocation que si les appels nous sont AUSSI
    # refusés. L'avis dit la cause, l'appel dit le fait.
    revoked_at: datetime | None
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime
    updated_at: datetime


class AssignedEnvironmentOut(BaseModel):
    """L'environnement rattaché, et QUAND on l'a appris. Les trois vont ensemble.

    La date voyage avec la valeur plutôt qu'à côté : un écran qui recevrait l'une sans
    l'autre afficherait un repli comme une lecture fraîche, et c'est exactement ce que ce
    ticket interdit.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    label: str
    fetched_at: datetime


class AssignedEnvironmentViewOut(BaseModel):
    """Ce que l'écran reçoit : la valeur, et si elle vient d'être relue chez le pair.

    `fresh` ne se déduit PAS de `environment` : « le pair est injoignable et on n'a jamais
    rien su » et « le pair dit qu'aucun environnement ne nous est rattaché » rendent tous
    deux `environment: null`, et les confondre annoncerait « aucun environnement » à un
    administrateur dont le réseau est coupé.
    """

    model_config = ConfigDict(extra="forbid")

    environment: AssignedEnvironmentOut | None
    fresh: bool


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
        contact_url=peer.contact_url,
        revoked_at=peer.revoked_at,
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


def assigned_environment_out(vue: AssignedEnvironmentView) -> AssignedEnvironmentViewOut:
    return AssignedEnvironmentViewOut(
        environment=(
            None
            if vue.environment is None
            else AssignedEnvironmentOut(
                slug=vue.environment.slug,
                label=vue.environment.label,
                fetched_at=vue.environment.fetched_at,
            )
        ),
        fresh=vue.fresh,
    )
