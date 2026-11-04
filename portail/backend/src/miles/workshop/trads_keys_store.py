from __future__ import annotations

from miles_socle.events.model import EventAuthor

from miles.git.workcopy import BranchMovedError, WorkCopy
from miles.workshop.target import WorkBranches
from miles.workshop.trads import contexts_in, culture_file, cultures_in
from miles.workshop.trads_keys_errors import (
    ConcurrentEditError,
    UnknownCultureError,
)
from miles.workshop.trads_values import (
    EmptyDefaultError,
    Key,
    checked_value,
    values_of,
    values_text,
)
from miles.workspaces.cultures import WorkspaceCultures
from miles.workspaces.model import WorkspaceConflictError


async def commit_or_refuse(
    branches: WorkBranches, copy: WorkCopy, message: str, author: EventAuthor
) -> str:
    try:
        return await branches.commit(copy, message, author)
    except BranchMovedError:
        raise ConcurrentEditError from None


async def must_exist(copy: WorkCopy, context: str) -> list[str]:
    paths = await copy.paths()
    if context not in contexts_in(paths):
        raise WorkspaceConflictError("contexte_inconnu")
    return paths


async def read_keys(copy: WorkCopy, context: str, cultures: WorkspaceCultures) -> list[Key]:
    """Toutes les clés du contexte, avec leurs valeurs dans les cultures du workspace.

    Les cultures du DÉPÔT donnent la liste des clés — un fichier resté là après le retrait
    d'une culture porte toujours les siennes — mais seules les cultures du workspace
    apparaissent dans les valeurs rendues (critère 17).
    """
    paths = await copy.paths()
    by_culture = {}
    for culture in cultures_in(paths, context):
        path = culture_file(context, culture)
        by_culture[culture] = values_of(path, await copy.read(path))
    slugs = sorted({slug for values in by_culture.values() for slug in values})
    keys = []
    for slug in slugs:
        values = {
            culture: by_culture[culture][slug]
            for culture in cultures.all
            if slug in by_culture.get(culture, {})
        }
        keys.append(Key(slug, values))
    return keys


async def write_cultures(
    copy: WorkCopy, context: str, changes: dict[str, dict[str, str | None]]
) -> None:
    """Réécrit uniquement les fichiers des cultures que la saisie touche."""
    touched = {culture for values in changes.values() for culture in values}
    for culture in touched:
        path = culture_file(context, culture)
        values = values_of(path, await copy.read(path))
        for slug, wanted in changes.items():
            if culture not in wanted:
                continue
            value = wanted[culture]
            if value is None:
                # Vidée : la ligne DISPARAÎT du fichier plutôt que d'y rester vide, et la
                # clé redevient non couverte dans cette culture (critère 5).
                values.pop(slug, None)
            else:
                values[slug] = value
        await copy.write(path, values_text(values))


def checked_values(
    values: dict[str, str | None], cultures: WorkspaceCultures, *, creating: bool
) -> dict[str, str | None]:
    """Valide les valeurs reçues et refuse ce qui viderait la culture par défaut."""
    unknown = [culture for culture in values if culture not in cultures.all]
    if unknown:
        raise UnknownCultureError(unknown[0])
    checked: dict[str, str | None] = {}
    for culture, value in values.items():
        if value is None or value == "":
            if culture == cultures.default:
                # La valeur de la culture par défaut est obligatoire (critères 2 et 6) :
                # sans elle, la clé n'aurait plus de valeur de référence, et l'écran de
                # saisie ne saurait plus la présenter.
                raise EmptyDefaultError(cultures.default)
            checked[culture] = None
        else:
            checked[culture] = checked_value(value)
    if creating and cultures.default not in checked:
        raise EmptyDefaultError(cultures.default)
    return checked


def matches(key: Key, search: str, untranslated: str | None) -> bool:
    if search and search.lower() not in key.slug.lower():
        return False
    return untranslated is None or untranslated not in key.values
