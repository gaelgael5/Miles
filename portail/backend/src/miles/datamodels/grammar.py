from __future__ import annotations

from dataclasses import dataclass

from miles_socle.parametrage.layout import NAME_RE as NAME_RE
from miles_socle.parametrage.yaml_read import MAX_TEXT_BYTES as MAX_TEXT_BYTES
from miles_socle.parametrage.yaml_read import ParametrageSyntaxError
from miles_socle.parametrage.yaml_read import load_yaml as load_yaml

# Lecture YAML commune aux documents du paramétrage (modèles, contrats, sources). Le
# contenu des modèles, lui, se vérifie en JSON Schema 2020-12 (datamodels/schema.py).


@dataclass(frozen=True)
class Problem:
    """Un manquement à la grammaire ; `path` désigne l'endroit dans le document."""

    path: str
    code: str
    detail: str | None = None


# ALIAS, et non une sous-classe : le lecteur YAML est au socle depuis le 02/11/2026,
# donc c'est LUI qui lève. Une sous-classe laisserait passer l'erreur du socle à
# travers tous les « except ModelSyntaxError » du produit, qui ne l'attraperaient plus.
ModelSyntaxError = ParametrageSyntaxError


class ModelGrammarError(ValueError):
    """YAML lisible mais non conforme : TOUS les manquements, pas seulement le premier."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(f"{len(problems)} manquement(s) à la grammaire")
        self.problems = problems
