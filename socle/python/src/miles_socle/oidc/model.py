from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit

CONNECTOR_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_SCOPE_RE = re.compile(r"^[A-Za-z0-9_:./-]{1,100}$")
_CLAIM_RE = re.compile(r"^[A-Za-z0-9_:./-]{1,100}$")
DEFAULT_GROUPS_CLAIM = "groups"
DEFAULT_DISPLAY_NAME_CLAIM = "name"
MAX_ISSUER_LENGTH = 500
MAX_CLIENT_ID_LENGTH = 200
MAX_LABEL_LENGTH = 200
DEFAULT_SCOPES = "openid email profile"
# Repli garanti de tout libellé déclinable : seul libellé obligatoire (ticket 2dbfb065).
LABEL_CULTURE = "en-US"
CULTURE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
OIDC_SECRET_TYPE = "OIDC_CLIENT_SECRET"  # noqa: S105  # nom du type, pas une valeur


class OidcError(Exception):
    """Refus lié aux connecteurs OIDC ; le message ne porte jamais de secret ni de jeton."""


class ConnectorInputError(OidcError):
    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


class ConnectorIdTakenError(OidcError):
    def __init__(self, connector_id: str) -> None:
        super().__init__(f"identifiant de connecteur déjà pris : {connector_id}")


class ConnectorNotFoundError(OidcError):
    def __init__(self, connector_id: str) -> None:
        super().__init__(f"connecteur inconnu : {connector_id}")
        self.connector_id = connector_id


class ConnectorInUseError(OidcError):
    """Des comptes sont déjà arrivés par ce connecteur : on le désactive, on ne le supprime pas."""

    def __init__(self, connector_id: str, identities: int) -> None:
        super().__init__(f"{identities} identité(s) arrivée(s) par {connector_id}")
        self.connector_id, self.identities = connector_id, identities


@dataclass(frozen=True)
class ConnectorInput:
    issuer: str
    client_id: str
    client_secret_slug: str
    scopes: str
    active: bool
    # Libellé par culture. Une culture absente de la saisie n'est pas touchée (ses
    # libellés survivent à sa désactivation) ; une chaîne vide retire son libellé.
    labels: Mapping[str, str]
    groups_claim: str = DEFAULT_GROUPS_CLAIM
    display_name_claim: str = DEFAULT_DISPLAY_NAME_CLAIM
    # Deux pouvoirs, décochés par défaut (décision du 19/10/2026) : chacun ne s'accorde
    # que par la décision explicite d'un administrateur.
    recognize_admin: bool = False
    manage_associations: bool = False


@dataclass(frozen=True)
class Connector:
    id: str
    issuer: str
    client_id: str
    client_secret_slug: str
    scopes: str
    active: bool
    # Libellé en-US, celui du repli ; `labels` porte toutes les cultures saisies.
    label: str
    groups_claim: str
    display_name_claim: str
    recognize_admin: bool
    manage_associations: bool
    created_at: datetime
    updated_at: datetime
    labels: Mapping[str, str] = field(default_factory=dict)


def validate_connector_id(connector_id: str) -> str:
    if not CONNECTOR_ID_RE.match(connector_id):
        raise ConnectorInputError("id")
    return connector_id


def validate_issuer(issuer: str, allow_http: bool) -> str:
    issuer = issuer.strip()
    parts = urlsplit(issuer)
    schemes = {"https", "http"} if allow_http else {"https"}
    # Ni identifiants, ni requête, ni fragment : l'émetteur se compare à l'octet près
    # au `iss` des jetons, et c'est de lui que se déduit l'adresse de découverte.
    if (
        len(issuer) > MAX_ISSUER_LENGTH
        or parts.scheme not in schemes
        or not parts.hostname
        or parts.username is not None
        or parts.query
        or parts.fragment
    ):
        raise ConnectorInputError("issuer")
    return issuer


def validate_scopes(scopes: str) -> str:
    tokens = scopes.split()
    if "openid" not in tokens or not all(_SCOPE_RE.match(t) for t in tokens):
        raise ConnectorInputError("scopes")
    return " ".join(dict.fromkeys(tokens))


def validate_input(raw: ConnectorInput, allow_http: bool) -> ConnectorInput:
    client_id = raw.client_id.strip()
    if not client_id or len(client_id) > MAX_CLIENT_ID_LENGTH:
        raise ConnectorInputError("client_id")
    labels = validate_labels(raw.labels)
    if not raw.client_secret_slug:
        raise ConnectorInputError("client_secret_slug")
    for claim_field in ("groups_claim", "display_name_claim"):
        if not _CLAIM_RE.match(getattr(raw, claim_field)):
            raise ConnectorInputError(claim_field)
    return ConnectorInput(
        issuer=validate_issuer(raw.issuer, allow_http),
        client_id=client_id,
        client_secret_slug=raw.client_secret_slug,
        scopes=validate_scopes(raw.scopes),
        active=raw.active,
        labels=labels,
        groups_claim=raw.groups_claim,
        display_name_claim=raw.display_name_claim,
        recognize_admin=raw.recognize_admin,
        manage_associations=raw.manage_associations,
    )


def validate_labels(raw: Mapping[str, str]) -> dict[str, str]:
    """Libellés saisis : le libellé en-US est exigé à chaque enregistrement.

    Raison : c'est lui que voit tout visiteur dont la culture n'a pas de libellé ; sans
    lui l'écran de connexion montrerait un identifiant technique ou un bouton vide.
    """
    labels: dict[str, str] = {}
    for culture, text in raw.items():
        if not CULTURE_RE.match(culture):
            raise ConnectorInputError("labels")
        value = text.strip()
        # Pas de troncature : deux libellés coupés au même endroit deviendraient identiques.
        if len(value) > MAX_LABEL_LENGTH:
            raise ConnectorInputError("labels")
        labels[culture] = value
    if not labels.get(LABEL_CULTURE):
        raise ConnectorInputError("label")
    return labels
