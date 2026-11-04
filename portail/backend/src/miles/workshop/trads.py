from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

from miles.workshop.reading import Read
from miles.workspaces.cultures import CULTURE_RE

# Référentiel de traductions du paramétrage (feature 52edade7) : `trads/<contexte>/<culture>.yaml`.
# Un fichier par contexte ET par culture, décidé à la feature : le diff ne montre alors
# qu'une langue à la fois, deux traducteurs de deux langues ne se marchent jamais dessus,
# et ajouter une culture n'altère aucun fichier existant. Un fichier unique portant toutes
# les cultures montrerait les langues côte à côte, mais tout changement toucherait tout le
# monde et deux traductions simultanées entreraient en conflit sur chaque clé.
TRADS = "trads/"
_SUFFIX = ".yaml"
# Métadonnées du contexte : son LIBELLÉ, qui n'existe que pour l'humain. Dans le dépôt et
# non en base, parce que le dépôt fait foi (story 623898d1, critère 9) — une liste de
# contextes en base pourrait contredire ce qu'une branche contient.
CONTEXT_FILE = "contexte.yaml"
# Le nom technique d'un contexte est un nom de RÉPERTOIRE, et il entre dans tout ce qui
# référencera ses clés. Refusé avant tout usage en chemin : ni `.`, ni `..`, ni séparateur,
# donc jamais un chemin hors de `trads/`. Même jeu de caractères que le slug d'un domaine.
CONTEXT_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
LABEL_MAX = 120
_FORMAT_VERSION = 1


@dataclass(frozen=True)
class Context:
    """Un contexte tel que la branche le porte."""

    name: str
    # Le nom technique quand aucun libellé n'est déclaré : un répertoire créé à la main,
    # ou venu d'une autre branche, apparaît quand même (critère 9).
    label: str
    keys: int
    # Clés traduites par culture, pour repérer d'un regard celui qui est en retard
    # (critère 7). Les cultures sont celles du WORKSPACE, pas celles de l'application.
    translated: dict[str, int]
    # Cultures dont le dépôt porte un fichier alors que le workspace ne les retient plus,
    # et combien de valeurs chacune garde. Retirer une culture ne détruit rien — c'est
    # voulu —, mais sans ce compte personne ne saurait que ces fichiers existent encore.
    obsolete: dict[str, int]


class TradsFileError(Exception):
    """Un fichier de `trads/` n'a pas la forme attendue : on nomme le fichier.

    Pas de repli sur « zéro clé » : un fichier illisible rendrait une couverture fausse,
    donc un changement de culture par défaut accepté à tort. Le dépôt fait foi, et une
    incohérence du dépôt se dit au lieu de se compter comme un travail à faire.
    """

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path} : {reason}")
        self.path, self.reason = path, reason


def culture_file(context: str, culture: str) -> str:
    return f"{TRADS}{context}/{culture}{_SUFFIX}"


def context_file(context: str) -> str:
    return f"{TRADS}{context}/{CONTEXT_FILE}"


def checked_context(name: str) -> str:
    if not CONTEXT_RE.fullmatch(name):
        raise ValueError("nom de contexte invalide")
    return name


def checked_label(label: str) -> str:
    """Le libellé est pour l'humain : une ligne, et rien qui fausse un affichage."""
    label = label.strip()
    if not label or len(label) > LABEL_MAX or any(c in label for c in "\n\r\x00"):
        raise ValueError("libellé de contexte invalide")
    return label


def context_text(label: str) -> str:
    return yaml.safe_dump(
        {"format_version": _FORMAT_VERSION, "label": label},
        allow_unicode=True,
        sort_keys=True,
    )


def label_of(path: str, content: str | None, name: str) -> str:
    """Le libellé déclaré, ou le nom technique à défaut.

    Repli volontaire sur le nom : un répertoire créé à la main n'a pas ce fichier, et il
    doit apparaître dans la liste plutôt que disparaître ou faire échouer la lecture.
    """
    if content is None:
        return name
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise TradsFileError(path, "yaml illisible") from exc
    if not isinstance(data, dict):
        raise TradsFileError(path, "une mappe est attendue")
    label = data.get("label")
    return label if isinstance(label, str) and label.strip() else name


def contexts_in(paths: list[str]) -> list[str]:
    """Les contextes d'une branche : les répertoires de `trads/`, vides compris."""
    return sorted({p.split("/")[1] for p in paths if p.startswith(TRADS) and p.count("/") >= 2})


def cultures_in(paths: list[str], context: str) -> list[str]:
    """Les cultures pour lesquelles ce contexte porte un fichier, retirée ou non du workspace.

    Une culture retirée des réglages garde ses fichiers (critère 7) : c'est ce qui permet
    à ses valeurs de réapparaître telles quelles si on la remet (critère 8).
    """
    prefix = f"{TRADS}{context}/"
    names = (
        p[len(prefix) : -len(_SUFFIX)]
        for p in paths
        if p.startswith(prefix) and p.endswith(_SUFFIX) and "/" not in p[len(prefix) :]
    )
    # Filtré sur la FORME d'un code de culture, et non sur une liste de noms à exclure :
    # c'est ce qui écarte d'un coup `contexte.yaml` et tout fichier parasite, sans qu'un
    # fichier de métadonnées ajouté plus tard soit compté comme une langue.
    return sorted(n for n in names if CULTURE_RE.fullmatch(n))


def keys_of(path: str, content: str | None) -> set[str]:
    """Les clés d'un fichier de culture, dont la forme est une mappe plate `slug: valeur`.

    Plate, et non imbriquée : le slug d'une clé est ce que le paramétrage référencera, et
    une imbrication rendrait deux chemins différents porteurs du même slug. C'est aussi ce
    qui garde le diff lisible ligne à ligne.
    """
    if content is None:
        return set()
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise TradsFileError(path, "yaml illisible") from exc
    # Un fichier vide est une culture sans aucune valeur, pas une erreur : c'est l'état
    # d'une culture qu'on vient d'ajouter au workspace.
    if data is None:
        return set()
    if not isinstance(data, dict):
        raise TradsFileError(path, "une mappe de slug vers valeur est attendue")
    return {str(key) for key in data}


async def file_context_key_sets(
    read: Read, context: str, cultures: list[str]
) -> dict[str, set[str]]:
    """Les clés de CHAQUE fichier de culture, une seule lecture et une seule analyse par fichier.

    Rendues par culture plutôt que fusionnées : la couverture a besoin du total ET du
    détail, et les obtenir par deux parcours relisait puis réanalysait chaque fichier une
    seconde fois. Sur une dizaine de cultures et quelques milliers de clés, c'était la
    moitié du travail d'un affichage (story 82e60880, critère 10).
    """
    sets: dict[str, set[str]] = {}
    for culture in cultures:
        path = culture_file(context, culture)
        sets[culture] = keys_of(path, await read(path))
    return sets


async def file_context_keys(read: Read, context: str, cultures: list[str]) -> set[str]:
    """Toutes les clés déclarées dans ce contexte, toutes cultures du dépôt confondues.

    Il n'existe aucun registre des clés à côté des fichiers : le dépôt fait foi, et la
    liste des clés d'un contexte est donc l'union de celles que ses fichiers portent. Un
    registre parallèle aurait pu contredire le contenu d'une branche.
    """
    return _union(await file_context_key_sets(read, context, cultures))


def _union(sets: dict[str, set[str]]) -> set[str]:
    """L'union des clés de tous les fichiers ; vide quand il n'y a aucun fichier."""
    return set().union(*sets.values())


async def file_missing_keys(read: Read, paths: list[str], culture: str) -> int:
    """Combien de clés de la branche n'ont aucune valeur dans cette culture."""
    missing = 0
    for context in contexts_in(paths):
        sets = await file_context_key_sets(read, context, cultures_in(paths, context))
        # Une culture sans fichier dans ce contexte n'y a aucune valeur : toutes les clés
        # du contexte lui manquent.
        missing += len(_union(sets) - sets.get(culture, set()))
    return missing


async def file_contexts(read: Read, paths: list[str], cultures: list[str]) -> list[Context]:
    """Les contextes de la branche, avec leur libellé, leur nombre de clés et leur couverture.

    `cultures` : celles du workspace. Une culture du dépôt qui n'y est plus n'apparaît pas
    dans la couverture, mais ses clés comptent toujours parmi celles du contexte — son
    fichier est resté, et c'est voulu.
    """
    contexts = []
    for name in contexts_in(paths):
        known = cultures_in(paths, name)
        sets = await file_context_key_sets(read, name, known)
        declared = _union(sets)
        # Pas d'intersection avec `declared` : il EST l'union de ces mêmes jeux, donc les
        # clés d'un fichier y sont toutes. Une intersection ferait croire à une garde là
        # où elle ne peut rien retirer.
        translated = {c: len(sets[c]) if c in sets else 0 for c in cultures}
        obsolete = {c: len(sets[c]) for c in known if c not in cultures}
        meta = context_file(name)
        label = label_of(meta, await read(meta), name)
        contexts.append(Context(name, label, len(declared), translated, obsolete))
    return contexts
