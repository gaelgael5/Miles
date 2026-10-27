from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import yaml

# Nom de modèle et de domaine : il devient un nom de fichier ou de dossier du dépôt.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
MAX_TEXT_BYTES = 64 * 1024
# Lecture YAML commune aux documents du paramétrage (modèles, contrats, sources). Le
# contenu des modèles, lui, se vérifie en JSON Schema 2020-12 (datamodels/schema.py).


@dataclass(frozen=True)
class Problem:
    """Un manquement à la grammaire ; `path` désigne l'endroit dans le document."""

    path: str
    code: str
    detail: str | None = None


class ModelSyntaxError(ValueError):
    """YAML illisible : la position est rendue pour qu'on la retrouve dans l'éditeur."""

    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.message, self.line, self.column = message, line, column


class ModelGrammarError(ValueError):
    """YAML lisible mais non conforme : TOUS les manquements, pas seulement le premier."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"{len(problems)} manquement(s) à la grammaire")
        self.problems = problems


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader qui refuse les clés en double.

    PyYAML garde la dernière en silence : une propriété déclarée deux fois perdrait sa
    première définition sans que personne ne le voie.
    """


def _mapping(loader: _StrictLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"clé en double : {key}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_yaml(text: str, max_bytes: int = MAX_TEXT_BYTES) -> Any:
    if len(text.encode("utf-8")) > max_bytes:
        raise ModelSyntaxError("document trop volumineux", None, None)
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506  # SafeLoader strict
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        message = exc.problem or str(exc)
        if mark is None:
            raise ModelSyntaxError(message, None, None) from None
        # PyYAML compte à partir de 0 ; un éditeur, à partir de 1.
        raise ModelSyntaxError(message, mark.line + 1, mark.column + 1) from None
    except yaml.YAMLError as exc:
        raise ModelSyntaxError(str(exc), None, None) from None
