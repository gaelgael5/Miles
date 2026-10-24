from __future__ import annotations

import json
import re
from dataclasses import dataclass

from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.transform.jpath import property_keys

# Un storage (story 844f15ad) : une collection d'objets JSON stockés en base, son modèle,
# sa clé fonctionnelle et ce sur quoi on pourra la filtrer. Un fichier par storage, à la
# racine comme les sources et les chaînes : le dépôt est déjà propre à une application.
#
# Deux notions distinctes de la source de données (Gael, 24/10/2026) : un storage existe
# sans source — on y écrira par API ou par MCP —, et la source ne fait que le désigner.
ROOT = "storages"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
MODEL_RE = re.compile(r"^(?P<scope>[a-z0-9][a-z0-9-]{0,62})/(?P<name>[a-z][a-z0-9_]{0,62})$")
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\.yaml$")
_KEYS = {"nom", "modele", "cle", "indexables"}


@dataclass(frozen=True)
class Indexable:
    # Identifiant interne, déclaré et non calculé : un `crc32(jpath)` a des collisions,
    # et elles seraient silencieuses — deux propriétés sous la même clé d'index, sans
    # erreur visible. Un nom déclaré est aussi stable au renommage du jpath.
    name: str
    jpath: str


@dataclass(frozen=True)
class StorageDoc:
    name: str
    # « shared/site » ou « <domaine>/site » : le modèle des objets stockés.
    model: str
    # Jpath évalués sur l'objet STOCKÉ, et non sur un document source : une collection
    # alimentée par API directe n'a pas de document source (Gael, 24/10/2026).
    keys: tuple[str, ...]
    indexables: tuple[Indexable, ...]


@dataclass(frozen=True)
class StorageProblem:
    path: str
    code: str
    detail: str | None = None


def storage_path(name: str) -> str:
    return f"{ROOT}/{name}.yaml"


def names_in(paths: list[str]) -> list[str]:
    return sorted(m["name"] for m in map(_FILE_RE.match, paths) if m is not None)


def storage_text(doc: StorageDoc) -> str:
    # Valeurs écrites en chaînes JSON, qui sont aussi des chaînes YAML : un jpath porte
    # des « $ », « [ » et « : » qui changeraient la structure du fichier non échappés.
    def q(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [
        f"nom: {q(doc.name)}",
        f"modele: {q(doc.model)}",
        "cle:",
        *(f"  - {q(k)}" for k in doc.keys),
    ]
    if doc.indexables:
        lines.append("indexables:")
        lines += [f"  - nom: {q(i.name)}\n    jpath: {q(i.jpath)}" for i in doc.indexables]
    else:
        lines.append("indexables: []")
    return "\n".join(lines) + "\n"


def read_storage(text: str | None) -> StorageDoc | None:
    """Déclaration lue, ou None si le fichier est absent ou n'en a pas la forme."""
    try:
        data = load_yaml(text) if text is not None else None
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - _KEYS:
        return None
    keys, indexables = data.get("cle"), data.get("indexables") or []
    if not isinstance(keys, list) or not isinstance(indexables, list):
        return None
    try:
        return StorageDoc(
            _text(data.get("nom")),
            _text(data.get("modele")),
            tuple(_text(k) for k in keys),
            tuple(Indexable(_text(i.get("nom")), _text(i.get("jpath"))) for i in indexables),
        )
    except (TypeError, AttributeError):
        return None


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def form_problems(doc: StorageDoc) -> list[StorageProblem]:
    """Ce qui se vérifie sur la déclaration seule, sans lire la branche."""
    problems = []
    if not NAME_RE.match(doc.name):
        problems.append(StorageProblem("nom", "nom_invalide"))
    if not MODEL_RE.match(doc.model):
        problems.append(StorageProblem("modele", "modele_invalide", doc.model))
    if not doc.keys:
        # Sans clé, un objet ne se reconnaît pas d'une écriture à l'autre : pas de
        # réconciliation, donc chaque import empilerait des doublons.
        problems.append(StorageProblem("cle", "cle_vide"))
    for rank, key in enumerate(doc.keys):
        if property_keys(key) is None:
            problems.append(StorageProblem(f"cle[{rank}]", "chemin_de_propriete_attendu", key))
    if len(set(doc.keys)) != len(doc.keys):
        problems.append(StorageProblem("cle", "cle_doublee"))
    names = [i.name for i in doc.indexables]
    jpaths = [i.jpath for i in doc.indexables]
    for rank, item in enumerate(doc.indexables):
        if not NAME_RE.match(item.name):
            problems.append(StorageProblem(f"indexables[{rank}].nom", "nom_invalide", item.name))
        elif names.count(item.name) > 1:
            problems.append(StorageProblem(f"indexables[{rank}].nom", "nom_double", item.name))
        if jpaths.count(item.jpath) > 1:
            problems.append(StorageProblem(f"indexables[{rank}].jpath", "jpath_double", item.jpath))
    return problems
