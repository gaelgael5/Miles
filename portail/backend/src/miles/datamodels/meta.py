from __future__ import annotations

from typing import Any

import yaml

# Métadonnées d'un modèle, à côté de son schéma : sa version, que JSON Schema n'a pas et
# que le système tient seul (Gael, 23/10/2026) — 1 à la création, +1 à chaque
# enregistrement qui change le schéma. Le label, lui, est le `title` du schéma. Le point
# est interdit dans un nom de modèle : `<nom>.meta.yaml` ne se confond jamais avec un modèle.
META_SUFFIX = ".meta.yaml"
VERSION_KEY = "version"


def meta_path(model_path: str) -> str:
    return model_path.removesuffix(".yaml") + META_SUFFIX


def meta_text(version: int) -> str:
    return yaml.safe_dump({VERSION_KEY: version}, sort_keys=False)


def read_version(text: str | None) -> int:
    """La version enregistrée ; 0 sans fichier ou illisible.

    Repli voulu : un schéma posé hors de Miles (ou par un outil) n'a pas de métadonnées,
    son premier enregistrement par Miles le met alors en version 1.
    """
    if text is None:
        return 0
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError:
        return 0
    version = data.get(VERSION_KEY) if isinstance(data, dict) else None
    return version if isinstance(version, int) and not isinstance(version, bool) else 0
