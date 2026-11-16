"""Lecture YAML des documents du paramétrage, commune aux produits qui les lisent.

Déplacée du module de paramétrage le 02/11/2026, à l'identique : le module
d'environnement lit les mêmes fichiers, et deux lecteurs auraient fini par accepter des
documents différents — celui qui refuse une clé en double et celui qui l'oublie.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import yaml

if TYPE_CHECKING:
    # Les deux lecteurs n'ont pas d'ancêtre commun utilisable : `CSafeLoader` porte le
    # parseur C, `SafeLoader` le parseur pur Python. Alias de typage seulement — nommer
    # `yaml.CSafeLoader` à l'exécution échouerait là où libyaml manque, c'est-à-dire
    # exactement dans le cas que le repli sert.
    _Loader = type[yaml.SafeLoader] | type[yaml.CSafeLoader]

MAX_TEXT_BYTES = 64 * 1024


class ParametrageSyntaxError(ValueError):
    """YAML illisible : la position est rendue pour qu'on la retrouve dans l'éditeur."""

    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.message, self.line, self.column = message, line, column


# Le lecteur de PyYAML adossé à libyaml, quand l'environnement d'exécution le porte.
# Mesuré le 15/11/2026 sur host-test-37, sur les 200 documents YAML d'une branche réelle :
# 936 ms la passe avec le lecteur pur Python, 117 ms avec celui-ci — huit fois moins —, et
# le scanner pur Python pesait 77,9 % du temps propre du backend pendant une lecture.
#
# Repli volontaire sur le lecteur pur Python si libyaml manque : le service doit démarrer
# et lire partout. Les deux rendent les MÊMES verdicts et les mêmes positions d'erreur —
# vérifié document par document par les tests d'équivalence de ce module, et non déduit :
# un repli plus strict ou plus laxiste serait pire que l'absence de gain. Seul le libellé
# des erreurs de syntaxe de PyYAML diffère ; la ligne et la colonne, dont se sert
# l'éditeur, coïncident.
try:
    _FAST: _Loader | None = yaml.CSafeLoader
except AttributeError:  # pragma: no cover — libyaml absent de l'environnement
    _FAST = None


def strict_loader(base: _Loader) -> _Loader:
    """Un lecteur dérivé de `base` qui refuse les clés en double.

    PyYAML garde la dernière en silence : une propriété déclarée deux fois perdrait sa
    première définition sans que personne ne le voie.

    Rendu public pour que les tests puissent construire le lecteur de repli et comparer
    les deux sur les mêmes textes (critère 8 de l'enabler 1af50397). Le service, lui,
    n'en instancie qu'un : deux lecteurs qui décident, c'est ce que le déplacement au
    socle a supprimé.
    """
    loader = cast("_Loader", type(f"Strict{base.__name__}", (base,), {}))
    loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
    return loader


def _mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"clé en double : {key}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node)


PURE_LOADER = strict_loader(yaml.SafeLoader)
LOADER = strict_loader(_FAST) if _FAST is not None else PURE_LOADER


def load_yaml(text: str, max_bytes: int = MAX_TEXT_BYTES, loader: _Loader = LOADER) -> Any:
    """Lit un document du paramétrage ; refuse les clés en double et les textes trop gros.

    `loader` n'existe que pour les tests d'équivalence entre le lecteur libyaml et celui
    de repli : aucun appelant du service ne le passe, et la borne de taille s'applique
    avant toute analyse quel que soit le lecteur.
    """
    if len(text.encode("utf-8")) > max_bytes:
        raise ParametrageSyntaxError("document trop volumineux", None, None)
    try:
        return yaml.load(text, Loader=loader)  # noqa: S506  # dérivé de SafeLoader, strict
    except yaml.MarkedYAMLError as exc:
        mark = exc.problem_mark or exc.context_mark
        message = exc.problem or str(exc)
        if mark is None:
            raise ParametrageSyntaxError(message, None, None) from None
        # PyYAML compte à partir de 0 ; un éditeur, à partir de 1.
        raise ParametrageSyntaxError(message, mark.line + 1, mark.column + 1) from None
    except yaml.YAMLError as exc:
        raise ParametrageSyntaxError(str(exc), None, None) from None
