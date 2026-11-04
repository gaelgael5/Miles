from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from miles.workspaces.model import WorkspaceConflictError, WorkspaceInputError

# Même forme que la colonne `cultures.code` : un code BCP 47. La clé étrangère vers le
# catalogue refuserait déjà l'inconnu, mais un code de culture devient un SEGMENT DE
# CHEMIN dans `trads/<contexte>/<culture>.yaml`, et le comptage de ce qui manque a lieu
# AVANT toute écriture — donc avant que la base n'ait pu trancher. Validé ici, à l'entrée,
# il ne peut jamais viser un fichier hors de `trads/`.
#
# Lue par `fullmatch` et non `match` : en Python, `$` accepte aussi la position AVANT un
# saut de ligne final, si bien que « fr-FR\n » passait la garde. Mesuré par le test, pas
# déduit — et un saut de ligne dans un nom de fichier est légal sous Linux.
CULTURE_RE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})*")

CULTURE_ADDED_EVENT = "workspace.culture_added"
CULTURE_REMOVED_EVENT = "workspace.culture_removed"
DEFAULT_CULTURE_EVENT = "workspace.default_culture_set"
EVENT_TYPES = frozenset({CULTURE_ADDED_EVENT, CULTURE_REMOVED_EVENT, DEFAULT_CULTURE_EVENT})

SELECT_CULTURES = (
    "SELECT culture, is_default FROM workspace_cultures WHERE workspace_id = $1"
    # La culture par défaut en premier, les additionnelles par code ensuite : l'ordre est
    # celui que les écrans montrent (critère 2) et il est stable d'une ligne à l'autre,
    # ce dont la table de saisie a besoin pour que ses colonnes ne dansent pas.
    " ORDER BY is_default DESC, culture"
)


@dataclass(frozen=True)
class WorkspaceCultures:
    """Les langues du PARAMÉTRAGE d'un workspace, pas celles de l'outil (story 639c25da)."""

    default: str
    additional: tuple[str, ...]

    @property
    def all(self) -> tuple[str, ...]:
        return (self.default, *self.additional)


class DefaultCultureIncompleteError(WorkspaceConflictError):
    """Changement de culture par défaut refusé : des clés n'ont pas de valeur dedans.

    Les clés existantes portent une valeur obligatoire dans l'ANCIENNE culture par défaut,
    et rien ne garantit qu'elles en aient une dans la nouvelle (critère 6). Accepter
    laisserait le référentiel avec des clés sans valeur obligatoire, état qu'aucun écran
    ne sait plus réparer puisqu'il n'est plus atteignable par la saisie.
    """

    def __init__(self, culture: str, missing: int) -> None:
        super().__init__("culture_defaut_incomplete")
        self.culture, self.missing = culture, missing


class MissingDefaultCultureError(WorkspaceConflictError):
    """Le workspace n'a pas de culture par défaut, ce que la création garantit.

    Jamais rencontré en service normal : la ligne naît dans la transaction de création du
    workspace. On le nomme plutôt que de rendre une liste vide, qui ferait lire « aucune
    culture » là où l'état est incohérent.
    """

    def __init__(self) -> None:
        super().__init__("culture_defaut_absente")


def checked_culture(culture: str, field: str = "culture") -> str:
    """`field` : le nom du champ saisi, pour que le refus désigne celui de l'écran."""
    if not CULTURE_RE.fullmatch(culture):
        raise WorkspaceInputError(field, "forme")
    return culture


def cultures_from_rows(rows: list[Any]) -> WorkspaceCultures:
    default = next((r["culture"] for r in rows if r["is_default"]), None)
    if default is None:
        raise MissingDefaultCultureError
    return WorkspaceCultures(default, tuple(r["culture"] for r in rows if not r["is_default"]))


async def db_cultures(db: Any, workspace_id: str) -> WorkspaceCultures:
    return cultures_from_rows(await db.fetch(SELECT_CULTURES, workspace_id))


async def db_insert_default(db: Any, workspace_id: str, culture: str) -> None:
    """Pose la culture par défaut à la création ; appelée dans la transaction du workspace."""
    await db.execute(
        "INSERT INTO workspace_cultures (workspace_id, culture, is_default) VALUES ($1, $2, true)",
        workspace_id,
        culture,
    )


async def db_add_culture(db: Any, workspace_id: str, culture: str) -> bool:
    """Ajoute une culture additionnelle ; rend faux si elle y était déjà.

    Idempotence portée par la clé primaire, et non par une lecture préalable : entre un
    SELECT et un INSERT, deux appels concurrents passent tous les deux. C'est aussi ce qui
    refuse la culture par défaut comme additionnelle (critère 4) sans la relire.
    """
    row = await db.fetchrow(
        "INSERT INTO workspace_cultures (workspace_id, culture, is_default)"
        " VALUES ($1, $2, false) ON CONFLICT DO NOTHING RETURNING culture",
        workspace_id,
        culture,
    )
    return row is not None


async def db_remove_culture(db: Any, workspace_id: str, culture: str) -> bool:
    """Retire une culture additionnelle ; rend faux si elle n'y était pas.

    La clause `NOT is_default` est la garde : la culture par défaut est obligatoire, et
    la retirer laisserait le workspace sans repli pour ses clés.
    """
    row = await db.fetchrow(
        "DELETE FROM workspace_cultures WHERE workspace_id = $1 AND culture = $2"
        " AND NOT is_default RETURNING culture",
        workspace_id,
        culture,
    )
    return row is not None


async def db_switch_default(db: Any, workspace_id: str, culture: str) -> None:
    """Bascule le drapeau de défaut ; l'ancienne devient additionnelle et garde ses valeurs.

    L'ordre compte : l'index unique partiel n'admet qu'une seule ligne par défaut, donc
    l'ancienne se dégrade AVANT que la nouvelle ne se promeuve. À appeler dans une
    transaction, pour cette raison exactement : le refus ci-dessous survient après la
    dégradation, et hors transaction le workspace resterait sans culture par défaut.
    """
    await db.execute(
        "UPDATE workspace_cultures SET is_default = false WHERE workspace_id = $1 AND is_default",
        workspace_id,
    )
    promoted = await db.fetchrow(
        "UPDATE workspace_cultures SET is_default = true"
        " WHERE workspace_id = $1 AND culture = $2 RETURNING culture",
        workspace_id,
        culture,
    )
    if promoted is None:
        # La nouvelle défaut doit déjà être une culture du workspace : promouvoir une
        # culture inconnue du workspace sauterait l'étape d'ajout, où elle est validée
        # contre le catalogue.
        raise WorkspaceInputError("culture", "absente_du_workspace")
