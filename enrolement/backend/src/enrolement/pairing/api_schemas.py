from __future__ import annotations

from datetime import datetime
from uuid import UUID

from miles_socle.signing.identity_model import ModuleIdentity
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import MAX_BASE_URL_LENGTH
from pydantic import BaseModel, ConfigDict, Field

from enrolement.pairing.model import (
    EnvironmentPeer,
    EnvironmentRef,
    PairingCode,
    PairingRequest,
)

# Les FORMES que les routes d'administration rendent, et la traduction du modèle vers
# elles. Séparées des routes parce que ce sont deux choses qu'on relit pour des raisons
# différentes : ici on vérifie ce qui SORT — et en particulier qu'aucune clé privée n'a
# de champ —, là-bas on vérifie qui a le droit d'appeler.


class IdentityOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # La clé PUBLIQUE sort, et c'est sa raison d'être : les environnements appariés en ont
    # besoin pour vérifier nos appels. La clé privée n'a aucun champ ici.
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime


class EnvironmentRefOut(BaseModel):
    """L'environnement du référentiel, juste de quoi le nommer à l'écran.

    L'identifiant est STABLE, le slug et le libellé sont renommables : l'écran affiche les
    seconds et renvoie le premier. Volontairement plus étroit que la forme du référentiel,
    qui porte en plus l'origine appariée — ici, ce serait l'appariement qui la porte.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    label: str


class EnvironmentDesignationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: UUID


class RequestOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    # Texte libre venu d'un tiers que personne n'a encore authentifié. Il aide un humain à
    # reconnaître la demande qu'il accepte, et n'identifie RIEN : deux demandes peuvent
    # porter le même, seule l'URL les distingue. Nul si la demande est antérieure au nom
    # déclaré. React l'échappe à l'affichage ; il n'est ni un identifiant ni une clef.
    name: str | None
    # L'empreinte, et non la clé : c'est elle qu'un humain compare à ce que l'écran de
    # l'environnement affiche, avant d'accepter.
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime
    expires_at: datetime
    # L'environnement DÉSIGNÉ par un humain authentifié. Nul tant que personne n'a choisi,
    # et c'est alors le code qui n'est pas révélable. Ne pas le confondre avec `name`
    # ci-dessus : l'un vient d'un inconnu et aide à reconnaître, l'autre désigne.
    environment: EnvironmentRefOut | None


class CodeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    code: str
    # De quoi afficher le temps restant : sans lui, l'humain ne sait pas s'il lui reste
    # vingt-neuf secondes ou une, et colle un code périmé dont le refus ressemble à un
    # code faux.
    seconds_remaining: int


class PeerOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    name: str | None
    # Nombre de devices que ce module a affectés à cet environnement. Il rend la
    # révocation décidable : révoquer un environnement qui porte des devices n'est pas le
    # même geste que révoquer un environnement vide (ticket ce66f5bb).
    #
    # NUL aujourd'hui, et c'est un refus de mentir : le référentiel des devices n'existe
    # pas encore (ticket de dispatch). Écrire 0 afficherait « aucun device » sur un écran
    # qui ne sait pas compter, et personne ne distinguerait plus « vide » d'« ignoré ».
    # Le champ existe pour que l'écran dise « — » dès maintenant, et la vérité ensuite.
    device_count: int | None
    public_key: str
    public_key_fingerprint: str
    algorithm: str
    created_at: datetime
    updated_at: datetime
    # Nul UNIQUEMENT pour les appariements hérités, conclus avant que la désignation
    # n'existe : l'écran les signale « à rattacher ». Aucun appariement neuf ne peut plus
    # se conclure sans — c'est un état transitoire hérité, pas un état admis.
    environment: EnvironmentRefOut | None
    # L'adresse où JOINDRE cette stack, saisie par l'administrateur de CE module.
    # Elle n'entre dans aucune signature et ne vaut jamais identité : l'origine
    # déclarée d'un appel entrant se compare à `base_url`, et à elle seule.
    contact_url: str


def environment_out(environnement: EnvironmentRef | None) -> EnvironmentRefOut | None:
    if environnement is None:
        return None
    return EnvironmentRefOut(
        id=environnement.id, slug=environnement.slug, label=environnement.label
    )


def request_out(demande: PairingRequest) -> RequestOut:
    return RequestOut(
        base_url=demande.base_url,
        name=demande.name,
        public_key_fingerprint=fingerprint(demande.public_key),
        algorithm=demande.algorithm,
        created_at=demande.created_at,
        expires_at=demande.expires_at,
        environment=environment_out(demande.environment),
    )


def peer_out(pair: EnvironmentPeer) -> PeerOut:
    return PeerOut(
        base_url=pair.base_url,
        name=pair.name,
        device_count=None,
        public_key=pair.public_key,
        public_key_fingerprint=fingerprint(pair.public_key),
        algorithm=pair.algorithm,
        created_at=pair.created_at,
        updated_at=pair.updated_at,
        environment=environment_out(pair.environment),
        contact_url=pair.contact_url,
    )


class ContactUrlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_url: str = Field(max_length=MAX_BASE_URL_LENGTH)


def code_out(code: PairingCode) -> CodeOut:
    return CodeOut(base_url=code.base_url, code=code.code, seconds_remaining=code.seconds_remaining)


def identity_out(identity: ModuleIdentity) -> IdentityOut:
    return IdentityOut(
        public_key=identity.public_key,
        public_key_fingerprint=fingerprint(identity.public_key),
        algorithm=identity.algorithm,
        created_at=identity.created_at,
    )
