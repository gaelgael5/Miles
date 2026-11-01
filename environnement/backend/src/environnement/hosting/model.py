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

HOSTING_OBJECT_KIND = "hosted_version"
VERSION_SERVED_EVENT = "hosting.version_served"
VERSION_REFUSED_EVENT = "hosting.version_refused"
EVENT_TYPES = frozenset({VERSION_SERVED_EVENT, VERSION_REFUSED_EVENT})

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
