from __future__ import annotations

from typing import Any

import yaml

# Métadonnées d'un modèle (Gael, 23/10/2026) : son label, dans un fichier à côté de son
# YAML, pour que le YAML et sa grammaire ne changent pas de forme. Le point est interdit
# dans un nom de modèle : `<nom>.meta.yaml` ne se confond jamais avec un modèle.
META_SUFFIX = ".meta.yaml"
LABEL_KEY = "libelle"


def meta_path(model_path: str) -> str:
    return model_path.removesuffix(".yaml") + META_SUFFIX


def meta_text(label: str) -> str:
    return yaml.safe_dump({LABEL_KEY: label}, allow_unicode=True, sort_keys=False)


def read_label(text: str | None) -> str | None:
    """Le label, ou None : pas de fichier (modèle créé par YAML ou par MCP), ou illisible."""
    if text is None:
        return None
    try:
        data: Any = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    label = data.get(LABEL_KEY) if isinstance(data, dict) else None
    return label if isinstance(label, str) and label.strip() else None


def skeleton(name: str) -> str:
    """Le YAML d'un modèle tout juste déclaré : un brouillon sans propriété."""
    return f"nom: {name}\nversion: 1\nproprietes: {{}}\n"
