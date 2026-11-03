"""Le sort de chaque objet d'un lot, et le compte-rendu du lot entier.

Rendu SYNCHRONEMENT à l'appelant pour les modes `element` et `tableau` (décision de Gael
du 02/11/2026 : « la méthode un element et la methode array ont le meme retour synchrone
avec un array qui décris pour chaque clef fonctionnel le retour »), et rangé sur la ligne
d'ingestion pour qu'un rejeu rende le même — un compte-rendu perdu avec la réponse HTTP
n'est pas une trace.

**Un objet rejeté n'est pas un échec d'import** (même décision) : le lot continue, et
c'est le compte-rendu qui nomme ce qui n'est pas passé. L'échec du LOT n'existe que
lorsque tout a été rejeté.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Le sort d'un objet. Trois issues, et la distinction entre les deux premières est tout
# l'objet de la story : `inchange` dit que la base n'a pas bougé, et c'est le DELTA
# constaté qui le dit, jamais le fait que le code ait tourné.
WRITTEN = "ecrit"
UNCHANGED = "inchange"
REJECTED = "rejete"

# Motifs de rejet d'un OBJET, distincts des refus de DÉPÔT (`model.py`) : ceux-ci
# n'empêchent pas le lot, ils nomment un objet.
REJECT_KEY_MISSING = "cle_non_extractible"
REJECT_TRANSFORM = "transformation_en_echec"
REJECT_MODEL = "modele_non_respecte"
REJECT_MANUAL = "objet_d_origine_manuelle"

# Anomalie de SOURCE, et non rejet : les deux objets sont traités, le dernier valide
# gagne (décision du 02/11/2026), et le compte-rendu le signale explicitement plutôt que
# d'écrire le dernier en silence (critère 8).
ANOMALY_DUPLICATE_KEY = "cle_en_double_dans_le_lot"

# État d'une ingestion, au-delà de « reçu » que la réception pose.
STATE_PROCESSED = "traite"
STATE_FAILED = "rejete"


@dataclass(frozen=True)
class ObjectOutcome:
    """Ce qu'un objet du lot est devenu. `position` est son rang, 0 pour le premier.

    `key` est nulle quand elle n'a pas pu être extraite : c'est précisément le cas où
    l'appelant ne peut pas se repérer par la clé, et le rang est alors sa seule prise
    (critère 9).
    """

    position: int
    outcome: str
    key: str | None = None
    reason: str | None = None
    detail: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "outcome": self.outcome,
            "key": self.key,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class Report:
    """Le compte-rendu du lot : les comptes, le sort de chaque objet, les anomalies."""

    received: int
    objects: list[ObjectOutcome] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)

    @property
    def written(self) -> int:
        return sum(1 for o in self.objects if o.outcome == WRITTEN)

    @property
    def unchanged(self) -> int:
        return sum(1 for o in self.objects if o.outcome == UNCHANGED)

    @property
    def rejected(self) -> int:
        return sum(1 for o in self.objects if o.outcome == REJECTED)

    @property
    def all_rejected(self) -> bool:
        """Tout a été rejeté, et il y avait quelque chose à traiter (critère 12).

        Un lot formellement valide mais VIDE n'est pas un échec : le ticket précédent
        l'accepte explicitement (son critère 5), et zéro objet rejeté sur zéro reçu ne
        doit pas faire tomber l'ingestion.
        """
        return self.received > 0 and self.rejected == self.received

    def as_json(self) -> dict[str, Any]:
        return {
            "received": self.received,
            "written": self.written,
            "unchanged": self.unchanged,
            "rejected": self.rejected,
            "objects": [o.as_json() for o in self.objects],
            "anomalies": self.anomalies,
        }


def report_of(data: Any) -> Report:
    """Le compte-rendu rangé en base, relu. Lève sur une forme inattendue.

    Lève plutôt que de rendre un compte-rendu partiel : un rejeu doit rendre CE qui a été
    décidé la première fois, et un compte-rendu amputé en silence ferait croire à un
    partenaire que son lot avait moins d'objets qu'il n'en a déposé. Si la forme a changé,
    c'est un défaut de migration, et il doit se voir.
    """
    objets = [
        ObjectOutcome(
            position=int(o["position"]),
            outcome=str(o["outcome"]),
            key=o["key"],
            reason=o["reason"],
            detail=o["detail"],
        )
        for o in data["objects"]
    ]
    return Report(received=int(data["received"]), objects=objets, anomalies=list(data["anomalies"]))
