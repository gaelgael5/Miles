"""Lire un modèle dans une copie ouverte : ce qu'il EST, et ce que ses renvois cachent.

Rien ici ne décide ni n'écrit : ce sont les gestes que tous les autres font avant de
décider. Les sortir du service laisse celui-ci se lire comme ce qu'il est — un
enchaînement de gestes de branche — et rend ces marches éprouvables sur une copie seule.
"""

from __future__ import annotations

from typing import Any

from miles_socle.parametrage.refs import inline_refs

from miles.datamodels.layout import ModelEntry, entry_of
from miles.datamodels.meta import meta_path, read_version
from miles.datamodels.schema import parse_schema
from miles.git.workcopy import WorkCopy


def entries_in(paths: list[str]) -> list[ModelEntry]:
    """Les modèles que ces chemins portent ; les autres fichiers sont ignorés."""
    return [e for e in map(entry_of, paths) if e is not None]


async def entries(copy: WorkCopy) -> list[ModelEntry]:
    return entries_in(await copy.paths())


async def described(copy: WorkCopy, entry: ModelEntry, text: str | None = None) -> ModelEntry:
    """Le modèle avec son label (le `title` du schéma) et sa version (ses métadonnées).

    `text` : le contenu déjà lu, quand l'appelant l'a sous la main. La liste en a besoin
    pour les usages, et le relire ici doublerait une lecture par modèle de la branche.
    """
    if text is None:
        text = await copy.read(entry.path)
    try:
        label = parse_schema(text or "").title
    except ValueError:
        # Illisible (retouché hors de Miles) : listé quand même, sans label ; la
        # validation de la branche dira pourquoi.
        label = None
    version = read_version(await copy.read(meta_path(entry.path)))
    return ModelEntry(entry.scope, entry.name, entry.path, label, version or None)


async def inlined_schema(copy: WorkCopy, schema: Any, origin: tuple[str, str]) -> Any:
    """Le schéma, renvois vers d'autres modèles remplacés par leur contenu.

    Exposé pour les documents qui partent du dépôt : un `$ref` vers « miles:/… » ne veut
    rien dire hors de Miles — ni pour un visualiseur Swagger, ni pour un appelant.

    La marche est au socle depuis le 02/11/2026 : le module d'environnement doit voir
    le MÊME schéma résolu, sans quoi l'écran proposerait une colonne qu'il refuserait.
    """

    async def read(path: str) -> str | None:
        return await copy.read(path)

    return await inline_refs(read, schema, origin)
