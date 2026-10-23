from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

# Nom de modèle et de domaine : il devient un nom de fichier ou de dossier du dépôt.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
PROPERTY_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
MAX_TEXT_BYTES = 64 * 1024
# Types admis au premier lot (Gael, 21/10/2026) : les scalaires usuels, l'énumération,
# l'objet qui désigne un autre modèle, et la liste. Pas de contrainte de valeur ni de
# cardinalité : le cadrage dit « simplement stocker un schéma YAML de description ».
SCALAR_TYPES = frozenset({"chaine", "entier", "decimal", "booleen", "date", "horodatage"})
TYPES = SCALAR_TYPES | {"enumeration", "objet", "liste"}
# Listes de listes admises, mais bornées : une imbrication sans fin ne décrit plus un
# objet métier, et la vérification doit rendre une erreur plutôt que s'y perdre.
MAX_LIST_DEPTH = 4
_TOP_KEYS = {"nom", "version", "description", "proprietes"}
_SPEC_KEYS = {"type", "valeurs", "modele", "elements"}


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


@dataclass(frozen=True)
class DataModel:
    name: str
    version: int
    # Modèles désignés par les propriétés `objet` : leur présence se vérifie dans le dépôt.
    references: tuple[tuple[str, str], ...] = field(default=())
    # Aucune propriété encore : un brouillon, admis à l'écriture (Gael, 23/10/2026) mais
    # qui bloque l'enregistrement d'une version de la branche.
    empty: bool = False


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


def parse_model(text: str) -> DataModel:
    """Lit et vérifie un modèle ; lève ModelSyntaxError ou ModelGrammarError."""
    data = load_yaml(text)
    checker = _Checker()
    model = checker.document(data)
    if checker.problems or model is None:
        raise ModelGrammarError(checker.problems)
    return model


class _Checker:
    def __init__(self) -> None:
        self.problems: list[Problem] = []
        self.references: list[tuple[str, str]] = []

    def fail(self, path: str, code: str, detail: str | None = None) -> None:
        self.problems.append(Problem(path, code, detail))

    def document(self, data: Any) -> DataModel | None:
        if not isinstance(data, dict):
            self.fail("", "document_non_objet")
            return None
        for key in sorted(set(map(str, data)) - _TOP_KEYS):
            self.fail(key, "cle_inconnue")
        name = data.get("nom")
        if not isinstance(name, str) or not NAME_RE.match(name):
            self.fail("nom", "obligatoire" if name is None else "nom_invalide")
        version = data.get("version")
        # bool est un int en Python : `version: true` ne doit pas passer pour 1.
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            self.fail("version", "obligatoire" if version is None else "version_invalide")
        if "description" in data and not isinstance(data["description"], str):
            self.fail("description", "texte_attendu")
        self.properties(data.get("proprietes"))
        if self.problems or not isinstance(version, int):
            return None
        empty = data.get("proprietes") == {}
        return DataModel(str(name), version, tuple(self.references), empty)

    def properties(self, value: Any) -> None:
        if value is None:
            self.fail("proprietes", "obligatoire")
            return
        if not isinstance(value, dict):
            self.fail("proprietes", "objet_attendu")
            return
        for key, spec in value.items():
            path = f"proprietes.{key}"
            if not isinstance(key, str) or not PROPERTY_RE.match(key):
                self.fail(path, "nom_de_propriete_invalide")
                continue
            if not isinstance(spec, dict):
                self.fail(path, "objet_attendu")
                continue
            extra = {"obligatoire"}
            if "obligatoire" in spec and not isinstance(spec["obligatoire"], bool):
                self.fail(f"{path}.obligatoire", "booleen_attendu")
            self.spec(path, spec, extra, depth=0)

    def spec(self, path: str, spec: dict[Any, Any], extra: set[str], depth: int) -> None:
        """Type d'une propriété ou des éléments d'une liste ; récursif sur `elements`."""
        for key in sorted(set(map(str, spec)) - _SPEC_KEYS - extra):
            self.fail(f"{path}.{key}", "cle_inconnue")
        kind = spec.get("type")
        if kind is None:
            self.fail(f"{path}.type", "obligatoire")
            return
        if kind not in TYPES:
            self.fail(f"{path}.type", "type_inconnu", str(kind))
            return
        self._only_for(path, spec, kind)
        if kind == "enumeration":
            self.values(f"{path}.valeurs", spec.get("valeurs"))
        elif kind == "objet":
            target = spec.get("modele")
            if not isinstance(target, str) or not NAME_RE.match(target):
                self.fail(f"{path}.modele", "obligatoire" if target is None else "nom_invalide")
            else:
                self.references.append((f"{path}.modele", target))
        elif kind == "liste":
            self.elements(f"{path}.elements", spec.get("elements"), depth + 1)

    def _only_for(self, path: str, spec: dict[Any, Any], kind: str) -> None:
        # Une clé d'un autre type serait ignorée en silence : on la refuse.
        for key, owner in (("valeurs", "enumeration"), ("modele", "objet"), ("elements", "liste")):
            if key in spec and kind != owner:
                self.fail(f"{path}.{key}", "cle_hors_type", owner)

    def elements(self, path: str, value: Any, depth: int) -> None:
        if value is None:
            self.fail(path, "obligatoire")
        elif not isinstance(value, dict):
            self.fail(path, "objet_attendu")
        elif depth > MAX_LIST_DEPTH:
            self.fail(path, "imbrication_trop_profonde", str(MAX_LIST_DEPTH))
        else:
            self.spec(path, value, set(), depth)

    def values(self, path: str, value: Any) -> None:
        if value is None:
            self.fail(path, "obligatoire")
            return
        if not isinstance(value, list) or not value:
            self.fail(path, "liste_non_vide_attendue")
            return
        # YAML 1.1 lit `on`, `off`, `yes`, `no` comme des booléens : une valeur non
        # textuelle trahit presque toujours ce piège, on la nomme plutôt que la convertir.
        if not all(isinstance(v, str) and v for v in value):
            self.fail(path, "valeurs_textuelles_attendues")
        elif len(set(value)) != len(value):
            self.fail(path, "valeurs_en_double")


def references_of(text: str) -> set[str]:
    """Modèles désignés par un document, même non conforme : pour protéger la suppression.

    Repli volontaire et tolérant : un fichier retouché à la main hors de Miles doit
    encore compter comme référençant, plutôt que laisser supprimer ce qu'il désigne.
    """
    try:
        data = load_yaml(text)
    except ModelSyntaxError:
        return set()
    found: set[str] = set()
    _collect(data, found)
    return found


def _collect(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        target = node.get("modele")
        if node.get("type") == "objet" and isinstance(target, str):
            found.add(target)
        for value in node.values():
            _collect(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect(value, found)
