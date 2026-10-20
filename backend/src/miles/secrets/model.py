from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import datetime

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
# Le type se choisit dans une liste (Gael, 20/10/2026), pas se tape : un type saisi
# à la main finit en variantes (GIT_TOKEN, GITHUB_TOKEN…) qu'aucun champ ne retrouve.
# La liste reste extensible : un consommateur nouveau ajoute ici son type, et son
# libellé dans les traductions du front. L'API refuse tout type absent d'ici.
SECRET_TYPES = (
    "OIDC_CLIENT_SECRET",  # secret client d'un connecteur OIDC
    "SECURITY_SERVICE_CLIENT_SECRET",  # accès au service de sécurité racine (Keycloak)
    "GIT_TOKEN",  # jeton ou mot de passe du compte de service git
    "GIT_CLIENT_KEY",  # clé privée du certificat client mTLS d'accès au dépôt
)
CONSUMER_KIND_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
MAX_LABEL_LENGTH = 200
# Large : une clé privée de certificat client tient dans un secret.
MAX_VALUE_LENGTH = 16 * 1024
MAX_CONSUMER_ID_LENGTH = 200
_MASK = "********"


class Secret:
    """Valeur secrète opaque : `.reveal()` est le seul accès au clair.

    Sa représentation affiche des astérisques : une valeur qui fuit dans un journal
    ou une f-string ne révèle rien. On ne la déballe qu'au point d'injection.
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Secret('{_MASK}')"

    def __str__(self) -> str:
        return _MASK

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        return hmac.compare_digest(self._value.encode(), other._value.encode())

    def __hash__(self) -> int:
        return hash(self._value)


class SecretError(Exception):
    """Base des refus du socle des secrets ; le message ne porte jamais de valeur."""


class SecretInputError(SecretError):
    """Saisie refusée ; `field` nomme le champ fautif."""

    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


class SecretNotFoundError(SecretError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"secret inconnu : {slug}")
        self.slug = slug


class SecretSlugTakenError(SecretError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"slug déjà pris : {slug}")
        self.slug = slug


class SecretTypeMismatchError(SecretError):
    def __init__(self, slug: str, expected: str, actual: str) -> None:
        super().__init__(f"secret {slug} de type {actual}, {expected} attendu")
        self.slug, self.expected, self.actual = slug, expected, actual


@dataclass(frozen=True)
class Consumer:
    kind: str
    id: str


class SecretInUseError(SecretError):
    def __init__(self, slug: str, consumers: tuple[Consumer, ...]) -> None:
        super().__init__(f"secret {slug} utilisé par {len(consumers)} objet(s)")
        self.slug, self.consumers = slug, consumers


class SecretUndecipherableError(SecretError):
    """Le chiffré ne s'ouvre pas : mauvaise clé, ligne altérée ou recopiée ailleurs."""

    def __init__(self, slug: str) -> None:
        super().__init__(f"secret indéchiffrable : {slug}")
        self.slug = slug


@dataclass(frozen=True)
class SecretSummary:
    """Ce qu'on peut montrer d'un secret : tout, sauf la valeur."""

    slug: str
    label: str
    secret_type: str
    created_at: datetime
    updated_at: datetime
    consumers: tuple[Consumer, ...]


def validate_slug(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise SecretInputError("slug")
    return slug


def validate_label(label: str) -> str:
    label = label.strip()
    if not label or len(label) > MAX_LABEL_LENGTH:
        raise SecretInputError("label")
    return label


def validate_secret_type(secret_type: str) -> str:
    if secret_type not in SECRET_TYPES:
        raise SecretInputError("secret_type")
    return secret_type


def validate_value(value: str) -> Secret:
    if not value or len(value) > MAX_VALUE_LENGTH:
        raise SecretInputError("value")
    # Une indirection ${…} n'est jamais une valeur saisie (règle du standard). Ici il
    # n'existe même aucune indirection : l'accepter ferait chiffrer, comme s'il était
    # le secret, un renvoi tapé à la main que rien ne résoudra.
    stripped = value.strip()
    if stripped.startswith("${") and stripped.endswith("}"):
        raise SecretInputError("value")
    return Secret(value)


def validate_consumer(consumer: Consumer) -> Consumer:
    if not CONSUMER_KIND_RE.match(consumer.kind):
        raise SecretInputError("consumer_kind")
    if not consumer.id or len(consumer.id) > MAX_CONSUMER_ID_LENGTH:
        raise SecretInputError("consumer_id")
    return consumer
