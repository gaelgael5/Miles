from __future__ import annotations

import json
import re
from dataclasses import dataclass

from urban_json.ast.nodes import JsltObject, JsltPath
from urban_json.jsonpath import IndexSelector, NameSelector, PathScope, WildcardSelector

from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.transform.engine import TemplateSyntaxError, parse_ast

# Une source de données (story 66391afe) : le référentiel d'objets qu'elle alimente, et
# comment elle le fait. Un fichier par source, à la racine comme les chaînes : le dépôt est
# déjà propre à une application.
ROOT = "sources"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
MODEL_RE = re.compile(r"^(?P<scope>[a-z0-9][a-z0-9-]{0,62})/(?P<name>[a-z][a-z0-9_]{0,62})$")
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\.yaml$")
_KEYS = {
    "nom",
    "modele",
    "decoupage",
    "cle",
    "chaine",
    "mode_gros_fichier",
    "transaction_unifiee",
    "filtrables",
}


@dataclass(frozen=True)
class Filterable:
    # Identifiant interne, déclaré et non calculé : un hash du jpath aurait des
    # collisions silencieuses, et changerait au moindre renommage du chemin.
    name: str
    jpath: str


@dataclass(frozen=True)
class SourceDoc:
    name: str
    # « shared/compte » ou « <domaine>/compte » : l'emplacement du modèle cible.
    model: str
    split: str
    keys: tuple[str, ...]
    chain: str
    large_file: bool
    unified_transaction: bool
    filterables: tuple[Filterable, ...]


@dataclass(frozen=True)
class SourceProblem:
    path: str
    code: str
    detail: str | None = None


def source_path(name: str) -> str:
    return f"{ROOT}/{name}.yaml"


def names_in(paths: list[str]) -> list[str]:
    return sorted(m["name"] for m in map(_FILE_RE.match, paths) if m is not None)


def source_text(doc: SourceDoc) -> str:
    # Valeurs écrites en chaînes JSON, qui sont aussi des chaînes YAML : un jpath porte
    # des « $ », « [ » et « : » qui changeraient la structure du fichier non échappés.
    def q(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        f"nom: {q(doc.name)}",
        f"modele: {q(doc.model)}",
        f"decoupage: {q(doc.split)}",
        "cle:",
        *(f"  - {q(k)}" for k in doc.keys),
        f"chaine: {q(doc.chain)}",
        f"mode_gros_fichier: {'true' if doc.large_file else 'false'}",
        f"transaction_unifiee: {'true' if doc.unified_transaction else 'false'}",
    ]
    if doc.filterables:
        lines.append("filtrables:")
        lines += [f"  - nom: {q(f.name)}\n    jpath: {q(f.jpath)}" for f in doc.filterables]
    else:
        lines.append("filtrables: []")
    return "\n".join(lines) + "\n"


def read_source(text: str | None) -> SourceDoc | None:
    """Déclaration lue, ou None si le fichier est absent ou n'en a pas la forme."""
    try:
        data = load_yaml(text) if text is not None else None
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - _KEYS:
        return None
    keys, filterables = data.get("cle"), data.get("filtrables") or []
    if not isinstance(keys, list) or not isinstance(filterables, list):
        return None
    try:
        return SourceDoc(
            _text(data.get("nom")),
            _text(data.get("modele")),
            _text(data.get("decoupage")),
            tuple(_text(k) for k in keys),
            _text(data.get("chaine")),
            _flag(data.get("mode_gros_fichier")),
            _flag(data.get("transaction_unifiee")),
            tuple(Filterable(_text(f.get("nom")), _text(f.get("jpath"))) for f in filterables),
        )
    except (TypeError, AttributeError):
        return None


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def _flag(value: object) -> bool:
    # Absent : faux. Les deux garanties se déclarent ; elles ne s'inventent pas.
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeError
    return value


def form_problems(doc: SourceDoc) -> list[SourceProblem]:
    """Ce qui se vérifie sur la déclaration seule, sans lire la branche."""
    problems = []
    if not NAME_RE.match(doc.name):
        problems.append(SourceProblem("nom", "nom_invalide"))
    if not MODEL_RE.match(doc.model):
        problems.append(SourceProblem("modele", "modele_invalide", doc.model))
    problems += _split_problems(doc.split)
    if not doc.keys:
        # Sans clé, un objet ne se reconnaît pas d'un envoi à l'autre : pas de réconciliation.
        problems.append(SourceProblem("cle", "cle_vide"))
    for rank, key in enumerate(doc.keys):
        if path_keys(key) is None:
            problems.append(SourceProblem(f"cle[{rank}]", "chemin_unique_attendu", key))
    names = [f.name for f in doc.filterables]
    jpaths = [f.jpath for f in doc.filterables]
    for rank, item in enumerate(doc.filterables):
        if not NAME_RE.match(item.name) or names.count(item.name) > 1:
            problems.append(SourceProblem(f"filtrables[{rank}].nom", "nom_invalide", item.name))
        if jpaths.count(item.jpath) > 1:
            problems.append(SourceProblem(f"filtrables[{rank}].jpath", "jpath_double", item.jpath))
    return problems


def _split_problems(split: str) -> list[SourceProblem]:
    """Le jpath de découpage doit se lire en flux : on ne revient pas en arrière en SAX.

    Admis : des noms ou des indices depuis la racine, puis un seul joker final qui désigne
    les items du tableau. Refusés : un filtre (il faudrait voir l'item entier avant de le
    garder), une descente `..` (non bornée), un joker qui ne termine pas le chemin.
    """
    if not split.strip():
        return [SourceProblem("decoupage", "decoupage_absent")]
    path = _path(split)
    if path is None:
        return [SourceProblem("decoupage", "jpath_illisible", split)]
    segments = path.compiled.segments
    if not segments:
        return [SourceProblem("decoupage", "non_streamable", "le chemin doit désigner un tableau")]
    for rank, segment in enumerate(segments):
        last = rank == len(segments) - 1
        if segment.is_recursive:
            return [SourceProblem("decoupage", "non_streamable", "descente « .. » non bornée")]
        selector = segment.selectors[0] if len(segment.selectors) == 1 else None
        if last and isinstance(selector, WildcardSelector):
            return []
        if not isinstance(selector, (NameSelector, IndexSelector)):
            reason = "un filtre exige l'item entier avant de le garder"
            if isinstance(selector, WildcardSelector):
                reason = "le joker doit terminer le chemin"
            return [SourceProblem("decoupage", "non_streamable", reason)]
    return [SourceProblem("decoupage", "non_streamable", "le chemin doit finir par [*]")]


def path_keys(text: str) -> tuple[str | int, ...] | None:
    """Un chemin depuis la racine, fait de noms et d'indices ; None sinon."""
    path = _path(text)
    if path is None or not path.compiled.is_singular or not path.compiled.segments:
        return None
    keys: list[str | int] = []
    for segment in path.compiled.segments:
        selector = segment.selectors[0]
        if isinstance(selector, NameSelector):
            keys.append(selector.name)
        elif isinstance(selector, IndexSelector):
            keys.append(selector.index)
        else:
            return None
    return tuple(keys)


def _path(text: str) -> JsltPath | None:
    # Lu par le parseur du moteur, dans un template minimal : jamais par une expression
    # maison, qui finirait par accepter ce que le moteur comprend autrement.
    try:
        ast = parse_ast(f'{{ "p": {text} }}')
    except TemplateSyntaxError:
        return None
    if not isinstance(ast, JsltObject):
        return None
    values = [p.value for p in ast.properties]
    path = values[0] if len(values) == 1 else None
    if not isinstance(path, JsltPath) or path.variable is not None:
        return None
    if path.compiled.scope is not PathScope.GLOBAL:
        return None
    return path
