from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from miles_socle.signing.keys import ALGORITHM

# La ligne unique des deux tables de l'identité : une seule valeur est admise par la
# contrainte de la base, et c'est elle. Le modèle, et non le code, interdit la seconde.
SINGLETON = "self"
# Slug du secret qui porte la clé privée. Constant et non configurable : c'est l'identité
# du module, pas une préférence d'exploitation, et un slug variable rendrait la ligne
# `module_identity` d'une installation illisible par l'outillage d'une autre.
SIGNING_KEY_SLUG = "identite-du-module"
SIGNING_KEY_LABEL = "Clé privée de signature du module d'environnement"
SIGNING_KEY_TYPE = "MODULE_SIGNING_KEY"
# L'usage déclaré du secret. Il ne sert pas à documenter : c'est lui qui fait refuser la
# suppression du secret par le socle, avec un 409 qui nomme le consommateur, au lieu de
# laisser l'écran des secrets buter sur la clé étrangère et rendre une erreur de serveur.
SIGNING_KEY_CONSUMER_KIND = "module_identity"
PUBLIC_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
BASE_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]{1,180}(:[0-9]{2,5})?$")
MAX_BASE_URL_LENGTH = 200


class IdentityError(Exception):
    """Base des refus de l'identité du module. Aucun message ne porte de clé privée."""


class IdentityInputError(IdentityError):
    """Saisie refusée ; `field` nomme le champ fautif."""

    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


class IdentityMissingError(IdentityError):
    """Aucune identité en base. Le module n'a pas encore démarré sur cette base."""


class IdentityInconsistentError(IdentityError):
    """La clé privée rangée ne correspond PAS à la clé publique déclarée.

    État anormal, et qui ne se répare pas tout seul : la clé publique est celle que le
    pair détient, donc signer avec une autre privée produirait des appels refusés chez
    lui, sans que rien ici ne soit rouge. On refuse de signer, bruyamment.

    Comment y arrive-t-on : la valeur du secret a été remplacée par l'écran générique des
    secrets, qui ne connaît pas la portée de ce qu'il remplace. Une régénération, elle,
    passe par la rotation de l'appariement, pas par là.
    """


class PeerMissingError(IdentityError):
    """Aucun module d'enrôlement apparié : il n'y a ni appel à émettre ni clé pour vérifier."""


class PeerRefusedError(IdentityError):
    """Le pair a REFUSÉ notre appel signé. À ne pas confondre avec « pair injoignable ».

    Les deux pannes se soignent autrement : un pair injoignable est un problème de réseau
    ou de déploiement, un pair qui refuse veut dire que la clé publique qu'il détient pour
    nous n'est pas celle que nous employons — un appariement à refaire. Les confondre
    enverrait le diagnostic du mauvais côté.
    """


class OriginMissingError(IdentityError):
    """Le module ne connaît pas sa propre adresse publique, et ne peut donc pas signer.

    L'origine entre dans ce qui est signé. Elle est CONFIGURÉE (MILES_PUBLIC_URL), jamais
    lue des en-têtes de la requête : un `Host` forgé ferait signer pour une autre origine
    que la sienne, et le pair enregistrerait cette origine comme la nôtre.
    """


@dataclass(frozen=True)
class ModuleIdentity:
    """Ce que le module peut montrer de son identité : tout, sauf la clé privée."""

    public_key: str
    algorithm: str
    created_at: datetime


@dataclass(frozen=True)
class EnrolmentPeer:
    """Le module d'enrôlement apparié : son origine et sa clé publique."""

    base_url: str
    public_key: str
    algorithm: str
    created_at: datetime
    updated_at: datetime


def validate_public_key(public_key: str) -> str:
    """Forme de la clé publique telle qu'elle est stockée : base64url de 32 octets.

    Vérifier la FORME ne vérifie pas que le pair détient la clé privée correspondante —
    `Ed25519PublicKey.from_public_bytes` accepte 32 octets quelconques (mesuré le
    28/10/2026). C'est le premier appel signé qui le prouve, jamais l'enregistrement.
    """
    if not PUBLIC_KEY_RE.match(public_key):
        raise IdentityInputError("public_key")
    return public_key


def validate_base_url(base_url: str) -> str:
    """Origine http(s) sans chemin. Entrée utilisateur : validée avant tout usage en URL."""
    base_url = base_url.strip().rstrip("/")
    if len(base_url) > MAX_BASE_URL_LENGTH or not BASE_URL_RE.match(base_url):
        raise IdentityInputError("base_url")
    return base_url


def validate_algorithm(algorithm: str) -> str:
    # Une seule valeur admise aujourd'hui, et la base le contraint aussi. Le champ existe
    # pour que les lignes déjà écrites disent ce qui les a signées le jour où il y en a deux.
    if algorithm != ALGORITHM:
        raise IdentityInputError("algorithm")
    return algorithm
