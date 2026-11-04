"""Ce qu'une clé d'API de cet environnement EST, et ce qu'elle ouvre."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime

# La mécanique de la clé vient du socle : fabrication, empreinte, préfixe affiché,
# comparaison en temps constant. Elle n'est pas recopiée du portail — une divergence du
# hachage ou de la comparaison serait un défaut de sécurité qu'aucun test ne signalerait.
from miles_socle.apikeys.model import KEY_RE

ISSUED_EVENT = "environment.api_key_issued"
GRANTS_EVENT = "environment.api_key_grants_changed"
REVOKED_EVENT = "environment.api_key_revoked"
EVENT_TYPES = frozenset({ISSUED_EVENT, GRANTS_EVENT, REVOKED_EVENT})
API_KEY_OBJECT_KIND = "api_key"
# Un libellé tient sur une ligne : il s'affiche dans la liste et dans le journal.
MAX_LABEL = 120


class KeyInputError(Exception):
    """Saisie refusée avant toute écriture ; `field` dit laquelle, `reason` pourquoi."""

    def __init__(self, field: str, reason: str = "invalide") -> None:
        super().__init__(f"{field}:{reason}")
        self.field, self.reason = field, reason


class UnknownSourceError(Exception):
    """Octroi vers une source que la version servie ne déclare pas."""

    def __init__(self, source: str, declared: tuple[str, ...]) -> None:
        super().__init__(source)
        self.source, self.declared = source, declared


@dataclass(frozen=True)
class ApiKeyInfo:
    """Ce qui se montre d'une clé : jamais la clé elle-même.

    `missing_sources` est un sous-ensemble de `sources` : les octrois que la version
    servie ne déclare plus. Rendu à l'écran, jamais corrigé d'office — l'octroi désigne
    un objet de la version, et une version suivante peut le ramener.
    """

    id: str
    label: str
    prefix: str
    sources: tuple[str, ...]
    missing_sources: tuple[str, ...]
    created_at: datetime
    created_by: str
    revoked_at: datetime | None
    last_used_at: datetime | None


@dataclass(frozen=True)
class KeyPrincipal:
    """L'appelant d'un dépôt : la clé, et ses octrois lus à l'instant de l'appel.

    Jamais mis en cache : une révocation ou un retrait d'octroi vaut dès la requête
    suivante. C'est ce qui fait qu'un geste de révocation est immédiat plutôt que
    « bientôt », et c'est la raison pour laquelle on relit à chaque dépôt.
    """

    key_id: str
    label: str
    sources: tuple[str, ...]

    def can_write(self, source: str) -> bool:
        # Pas de niveau d'accès : une clé d'ingestion écrit, c'est tout ce qu'elle fait.
        return source in self.sources


def checked_label(label: str) -> str:
    """Libellé saisi d'une clé : une ligne lisible.

    Écrit ici et non emprunté au portail : sa version lève une erreur de saisie de
    workspace, notion que ce produit n'a pas. L'extraction au socle de cette règle est un
    chantier à part — le portail en porte déjà deux copies —, et la faire ici changerait
    les messages de refus d'un autre produit.
    """
    label = label.strip()
    if not label:
        raise KeyInputError("label", "vide")
    # Caractères de contrôle refusés : le libellé s'affiche dans la liste et dans les
    # journaux, où un retour à la ligne ou une séquence d'échappement fausserait la
    # lecture — jusqu'à faire passer une ligne du journal pour une autre.
    if len(label) > MAX_LABEL or any(unicodedata.category(c) == "Cc" for c in label):
        raise KeyInputError("label")
    return label


def presented_key(raw: str | None) -> str | None:
    """La clé telle qu'elle est présentée, ou None si elle n'en a pas la forme.

    Vérifier la forme AVANT de toucher la base : une chaîne quelconque ne doit pas
    déclencher de requête, et la refuser ici évite que la durée de la réponse ne dise
    si une empreinte a été cherchée.
    """
    if raw is None or not KEY_RE.match(raw):
        return None
    return raw
