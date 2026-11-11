"""Où vivent les événements de workflow, et comment ils se nomment.

Un événement est un **JSON Schema 2020-12 écrit en YAML** — la même forme qu'un modèle de
données, et c'est ce qui permet de réutiliser l'écran de construction tel quel. Il est
rangé à part et listé à part (Gael, 11/11/2026) : sa propre liste, pour qu'aucun storage
ni aucune source ne le désigne par mégarde, et pour qu'un modèle ne devienne pas un
événement par une case cochée quelque part.

Ces chemins restent au PRODUIT, et c'est voulu : `miles_socle.parametrage.layout` porte
les chemins qu'un SECOND produit lit — le module d'environnement ingère des objets décrits
par un modèle, donc il a besoin de `model_path`. Personne ne lit encore les événements
hors du portail ; le jour où un moteur de workflow tournera dans un module
d'environnement, ils monteront au socle. Pas avant : on n'invente pas un socle commun
avant d'avoir deux usages à servir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from miles.datamodels.layout import SHARED as SHARED
from miles.workspaces.model import WorkspaceInputError

# Le nom d'un événement est PLUS ÉTROIT que celui d'un modèle, et c'est une MESURE, pas un
# excès de prudence : le DSL d'`urban-workflow` accepte `demande_soumise` et `demande2`
# mais REFUSE le tiret — `2:20: mismatched input '-' expecting ';'`, relevé le 11/11/2026
# sur urban-workflow 0.2.1. Un événement nommé avec un tiret serait donc impossible à
# écrire dans un `DEFINE EVENT`, c'est-à-dire un référentiel que le moteur ne peut pas
# nommer. Le refus est ici, à la saisie, plutôt que découvert au chargement d'un script.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")

# Les noms que le moteur se réserve — `__expired`, `__cancelReminderAction`, `$_result`,
# `$_reminder` — sont HORS D'ATTEINTE de `NAME_RE` : aucun ne commence par une minuscule
# ou un chiffre. Aucune liste noire à tenir, donc, et c'est mesuré et non supposé : la
# règle de nommage suffit à rendre la collision impossible.

# `$id` d'un événement. Le segment `events/` le met hors de portée de `target_of` (qui ne
# reconnaît que `miles:/shared/<nom>` et `miles:/domains/<d>/<nom>`) : un storage ou une
# source qui tenterait de désigner un événement ne le résoudra pas, ce qui est exactement
# la frontière voulue par le choix de la liste séparée.
ID_PREFIX = "miles:/events/"

_PATH_RE = re.compile(
    r"^(?:shared/events/(?P<shared>[a-z0-9][a-z0-9_]*)"
    r"|domains/(?P<domain>[^/]+)/events/(?P<name>[a-z0-9][a-z0-9_]*))\.yaml$"
)


@dataclass(frozen=True)
class EventEntry:
    scope: str  # « shared », ou le nom du domaine
    name: str
    path: str
    # Hors de l'égalité : un événement reste le même quel que soit son libellé ou sa
    # version — même raison que pour un modèle.
    label: str | None = field(default=None, compare=False)
    version: int | None = field(default=None, compare=False)


def event_path(scope: str, name: str) -> str:
    if scope == SHARED:
        return f"shared/events/{name}.yaml"
    return f"domains/{scope}/events/{name}.yaml"


def event_id(scope: str, name: str) -> str:
    if scope == SHARED:
        return f"{ID_PREFIX}shared/{name}"
    return f"{ID_PREFIX}domains/{scope}/{name}"


def entry_of(path: str) -> EventEntry | None:
    """L'événement qu'un chemin du dépôt désigne, ou None.

    Le nom suit `NAME_RE` : un fichier de métadonnées (`.meta.yaml`) porte un point, il
    n'est donc jamais pris pour un événement.
    """
    match = _PATH_RE.match(path)
    if match is None:
        return None
    if match["shared"] is not None:
        return EventEntry(SHARED, match["shared"], path)
    return EventEntry(match["domain"], match["name"], path)


def checked_scope(scope: str) -> str:
    # La portée d'un événement est celle d'un modèle : un nom de domaine suit la règle de
    # nommage des modèles (tiret admis), c'est le nom de l'ÉVÉNEMENT que le DSL contraint.
    if scope != SHARED and not re.match(r"^[a-z0-9][a-z0-9_-]{0,62}$", scope):
        raise WorkspaceInputError("scope")
    return scope


def checked_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise WorkspaceInputError("name")
    return name


def visible(entry: EventEntry, target: tuple[str, str]) -> bool:
    """Un événement de domaine peut décrire son payload avec un modèle de son domaine ou
    un modèle transverse ; un événement transverse, avec un transverse seulement — il ne
    peut pas dépendre d'un domaine sans cesser d'être transverse. Même règle que les
    modèles entre eux, et pour la même raison."""
    scope, _ = target
    return scope == SHARED or (entry.scope != SHARED and scope == entry.scope)
