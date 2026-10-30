from __future__ import annotations

import yaml

from miles.workshop.reading import Read

# Référentiel de traductions du paramétrage (feature 52edade7) : `trads/<contexte>/<culture>.yaml`.
# Un fichier par contexte ET par culture, décidé à la feature : le diff ne montre alors
# qu'une langue à la fois, deux traducteurs de deux langues ne se marchent jamais dessus,
# et ajouter une culture n'altère aucun fichier existant. Un fichier unique portant toutes
# les cultures montrerait les langues côte à côte, mais tout changement toucherait tout le
# monde et deux traductions simultanées entreraient en conflit sur chaque clé.
TRADS = "trads/"
_SUFFIX = ".yaml"


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


def contexts_in(paths: list[str]) -> list[str]:
    """Les contextes d'une branche : les répertoires de `trads/`, vides compris."""
    return sorted({p.split("/")[1] for p in paths if p.startswith(TRADS) and p.count("/") >= 2})


def cultures_in(paths: list[str], context: str) -> list[str]:
    """Les cultures pour lesquelles ce contexte porte un fichier, retirée ou non du workspace.

    Une culture retirée des réglages garde ses fichiers (critère 7) : c'est ce qui permet
    à ses valeurs de réapparaître telles quelles si on la remet (critère 8).
    """
    prefix = f"{TRADS}{context}/"
    return sorted(
        p[len(prefix) : -len(_SUFFIX)]
        for p in paths
        if p.startswith(prefix) and p.endswith(_SUFFIX) and "/" not in p[len(prefix) :]
    )


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


async def file_context_keys(read: Read, context: str, cultures: list[str]) -> set[str]:
    """Toutes les clés déclarées dans ce contexte, toutes cultures du dépôt confondues.

    Il n'existe aucun registre des clés à côté des fichiers : le dépôt fait foi, et la
    liste des clés d'un contexte est donc l'union de celles que ses fichiers portent. Un
    registre parallèle aurait pu contredire le contenu d'une branche.
    """
    keys: set[str] = set()
    for culture in cultures:
        path = culture_file(context, culture)
        keys |= keys_of(path, await read(path))
    return keys


async def file_missing_keys(read: Read, paths: list[str], culture: str) -> int:
    """Combien de clés de la branche n'ont aucune valeur dans cette culture."""
    missing = 0
    for context in contexts_in(paths):
        declared = await file_context_keys(read, context, cultures_in(paths, context))
        path = culture_file(context, culture)
        missing += len(declared - keys_of(path, await read(path)))
    return missing
