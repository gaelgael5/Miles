"""Lecture YAML des documents du paramétrage, commune aux produits qui les lisent.

Déplacée du module de paramétrage le 02/11/2026, à l'identique : le module
d'environnement lit les mêmes fichiers, et deux lecteurs auraient fini par accepter des
documents différents — celui qui refuse une clé en double et celui qui l'oublie.
"""

from __future__ import annotations

from typing import Any

import yaml

MAX_TEXT_BYTES = 64 * 1024


class ParametrageSyntaxError(ValueError):
    """YAML illisible : la position est rendue pour qu'on la retrouve dans l'éditeur."""

    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.message, self.line, self.column = message, line, column


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
        raise ParametrageSyntaxError("document trop volumineux", None, None)
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506  # SafeLoader strict
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        message = exc.problem or str(exc)
        if mark is None:
            raise ParametrageSyntaxError(message, None, None) from None
        # PyYAML compte à partir de 0 ; un éditeur, à partir de 1.
        raise ParametrageSyntaxError(message, mark.line + 1, mark.column + 1) from None
    except yaml.YAMLError as exc:
        raise ParametrageSyntaxError(str(exc), None, None) from None
