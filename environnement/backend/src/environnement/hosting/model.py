"""Ce que cette stack sert, et ce qui a pu l'empêcher.

Deux types d'event, pour deux questions que personne ne pose ensemble : « depuis quand
sert-on cette version ? » et « qu'est-ce qui a empêché la dernière mise à jour ? ». Un
event unique portant un état obligerait à interpréter ses propriétés pour répondre à l'une
ou à l'autre, et c'est ce journal qu'on viendra lire le jour où un device ne se comporte
pas comme son paramétrage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from miles_socle.events.catalog import EventShape, closed_block

HOSTING_OBJECT_KIND = "hosted_version"
VERSION_SERVED_EVENT = "hosting.version_served"
VERSION_REFUSED_EVENT = "hosting.version_refused"
# L'ORDRE reçu, que `_write_event` ajoute à TOUT event de ce module : le numéro de version
# et le commit ordonné. Mesuré le 12/11/2026, et la première version de ces formes les
# avait ratés — lire le site d'appel ne suffit pas quand un helper complète le bloc, et
# c'est la campagne d'intégration qui l'a dit. Une garde les tient désormais ensemble
# (`tests/test_formes_des_events.py`).
_ORDRE: dict[str, Any] = {
    "number": {"type": "integer", "minimum": 1},
    # DÉRIVÉ de `COMMIT_RE` ci-dessous, qui est la forme du CHECK de la migration 0015.
    "ordered_commit": {"type": "string", "pattern": r"^[0-9a-f]{40}$"},
}
# Deux blocs et non un seul portant les deux champs facultatifs : les deux questions ne
# se posent jamais ensemble, et un champ nul obligerait à l'interpréter pour savoir
# laquelle on relit.
EVENT_SHAPES = (
    EventShape(
        VERSION_SERVED_EVENT,
        "Version servie par cette stack",
        # `commit` est ce qu'on SERT ; `ordered_commit` ce qui avait été demandé. Les deux,
        # parce que le refus `commit_inattendu` existe précisément quand ils diffèrent.
        closed_block({**_ORDRE, "commit": {"type": "string", "pattern": r"^[0-9a-f]{40}$"}}),
    ),
    EventShape(
        VERSION_REFUSED_EVENT,
        "Version non servie",
        # Un motif et non une énumération : ce module en déclare onze, et les énumérer ici
        # ferait une douzième liste à tenir d'accord avec la première.
        closed_block(
            {**_ORDRE, "refusal": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,39}$"}}
        ),
    ),
)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)
# Les types que `HostingService._write_event` écrit, donc ceux dont le bloc doit
# déclarer l'ordre reçu. Nommés ici plutôt que recopiés dans le test : le jour où un
# troisième type passe par ce helper, il entre dans la garde tout seul.
EVENT_TYPES_ORDONNES: tuple[str, ...] = (VERSION_SERVED_EVENT, VERSION_REFUSED_EVENT)

# La MÊME forme que le CHECK de la migration 0015 : la base tient l'invariant pour de bon,
# le code est le seul à pouvoir refuser en nommant ce qui pèche.
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

# Les refus que ce module produit, et chacun nomme un geste différent chez l'enrôlement.
REFUSAL_NO_PEER = "aucun_pair"
REFUSAL_RELAY_UNREACHABLE = "relais_injoignable"
REFUSAL_RELAY_REFUSED = "relais_refuse"
# Le bundle est arrivé, mais la version qu'il porte n'est pas le commit ordonné. C'est LE
# refus qui fait tenir l'intégrité de l'échange : la réponse du relais n'est pas signée,
# et seul l'ordre — signé, lui — dit quel contenu est le bon.
REFUSAL_WRONG_COMMIT = "commit_inattendu"
REFUSAL_BUNDLE_UNREADABLE = "bundle_illisible"
REFUSAL_TOO_LARGE = "bundle_trop_volumineux"
REFUSAL_NO_ORIGIN = "origine_absente"


class HostingError(Exception):
    """Refus de l'hébergement d'une version ; le message dit lequel."""


class BundleRejectedError(HostingError):
    """Le contenu reçu ne porte pas le commit ordonné : il est jeté, rien n'est posé.

    Jamais « on garde au cas où » : un arbre posé depuis un contenu non vérifié servirait
    un paramétrage que personne n'a choisi, et il serait indiscernable du bon.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"contenu refusé : {reason}")
        self.reason = reason


@dataclass(frozen=True)
class HostedVersion:
    """L'ordre reçu, et la trace de ce qu'on en a fait.

    `served_commit` est ici une TRACE, pas la vérité : ce qui est réellement servi se lit
    dans l'arbre posé sur le volume (`git rev-parse HEAD`). Les deux peuvent diverger — un
    volume neuf après un redéploiement —, et c'est exactement pour ce cas que l'arbre est
    interrogé avant de décider qu'il n'y a rien à faire.
    """

    workspace_id: str
    ordered_number: int
    ordered_commit: str
    ordered_at: datetime
    served_commit: str | None
    served_at: datetime | None
    refusal: str | None
