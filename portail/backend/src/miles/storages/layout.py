from __future__ import annotations

import json
import re
from dataclasses import dataclass

from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.datamodels.layout import MODEL_RE
from miles.transform.jpath import property_keys

# Un storage (story 844f15ad) : une collection d'objets JSON stockés en base, son modèle,
# sa clé fonctionnelle et ce sur quoi on pourra la filtrer. Un fichier par storage, à la
# racine comme les sources et les chaînes : le dépôt est déjà propre à une application.
#
# Deux notions distinctes de la source de données (Gael, 24/10/2026) : un storage existe
# sans source — on y écrira par API ou par MCP —, et la source ne fait que le désigner.
ROOT = "storages"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\.yaml$")
_KEYS = {"nom", "libelle", "modele", "cle", "index", "indexables"}
# Un index porte de 1 à 3 colonnes (Gael, 24/10/2026). Le plafond est une décision, pas
# une limite technique : au-delà, un index composite ne sert plus les filtres attendus et
# coûte en écriture ce qu'il ne rend pas en lecture.
MAX_COLUMNS = 3


@dataclass(frozen=True)
class Index:
    """Un index additionnel : son nom, et les colonnes qu'il couvre, dans l'ordre.

    L'ordre compte — c'est celui d'un index composite : il sert les filtres sur la
    première colonne, puis sur les deux premières, etc. Le changer change ce qu'il sert.
    """

    # Identifiant interne, déclaré et non calculé : un `crc32` des colonnes aurait des
    # collisions, et elles seraient silencieuses — deux index sous la même clé, sans
    # erreur visible. Un nom déclaré est aussi stable au renommage d'une colonne.
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class StorageDoc:
    # Identifiant : il nomme le fichier, donc contraint à ce qui fait un nom de fichier.
    # Il se DÉDUIT du libellé à la création (comme un contrat ou une chaîne) : on ne fait
    # pas saisir un slug à la main pour se le voir refuser ensuite.
    name: str
    # Ce que la personne a écrit, et ce que les écrans affichent.
    label: str
    # « shared/site » ou « <domaine>/site » : le modèle des objets stockés.
    model: str
    # Jpath évalués sur l'objet STOCKÉ, et non sur un document source : une collection
    # alimentée par API directe n'a pas de document source (Gael, 24/10/2026).
    keys: tuple[str, ...]
    indexes: tuple[Index, ...]


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
        f"libelle: {q(doc.label)}",
        f"modele: {q(doc.model)}",
        "cle:",
        *(f"  - {q(k)}" for k in doc.keys),
    ]
    if doc.indexes:
        lines.append("index:")
        for item in doc.indexes:
            lines.append(f"  - nom: {q(item.name)}")
            lines.append("    colonnes:")
            lines += [f"      - {q(c)}" for c in item.columns]
    else:
        lines.append("index: []")
    return "\n".join(lines) + "\n"


def read_storage(text: str | None) -> StorageDoc | None:
    """Déclaration lue, ou None si le fichier est absent ou n'en a pas la forme."""
    try:
        data = load_yaml(text) if text is not None else None
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - _KEYS:
        return None
    keys = data.get("cle")
    if not isinstance(keys, list):
        return None
    indexes = _indexes(data)
    if indexes is None:
        return None
    try:
        return StorageDoc(
            _text(data.get("nom")),
            _text(data.get("libelle")),
            _text(data.get("modele")),
            tuple(_text(k) for k in keys),
            indexes,
        )
    except (TypeError, AttributeError):
        return None


def _indexes(data: dict[str, object]) -> tuple[Index, ...] | None:
    """Les index déclarés, l'ancienne forme `indexables` comprise.

    Avant le 24/10/2026 un index couvrait UNE propriété (`indexables: [{nom, jpath}]`).
    La conversion vers un index à une colonne est exacte et sans perte : on la fait, au
    lieu de rendre illisible une déclaration déjà écrite. Ce n'est pas un repli
    silencieux — la forme convertie est réécrite dès le premier enregistrement.
    """
    declared, legacy = data.get("index"), data.get("indexables")
    if declared is not None and legacy is not None:
        # Les deux formes à la fois : on ne devine pas laquelle fait foi.
        return None
    try:
        if legacy is not None:
            if not isinstance(legacy, list):
                return None
            return tuple(Index(_text(i.get("nom")), (_text(i.get("jpath")),)) for i in legacy)
        if declared is None:
            return ()
        if not isinstance(declared, list):
            return None
        return tuple(_one_index(i) for i in declared)
    except (TypeError, AttributeError):
        return None


def _one_index(raw: object) -> Index:
    columns = raw.get("colonnes") if isinstance(raw, dict) else None
    if not isinstance(columns, list):
        raise TypeError
    name = raw.get("nom") if isinstance(raw, dict) else None
    return Index(_text(name), tuple(_text(c) for c in columns))


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def form_problems(doc: StorageDoc) -> list[StorageProblem]:
    """Ce qui se vérifie sur la déclaration seule, sans lire la branche."""
    problems = []
    if not NAME_RE.match(doc.name):
        problems.append(StorageProblem("nom", "nom_invalide"))
    if not doc.label.strip():
        problems.append(StorageProblem("libelle", "libelle_vide"))
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
    names = [i.name for i in doc.indexes]
    for rank, item in enumerate(doc.indexes):
        where = f"index[{rank}]"
        if not NAME_RE.match(item.name):
            problems.append(StorageProblem(f"{where}.nom", "nom_invalide", item.name))
        elif names.count(item.name) > 1:
            problems.append(StorageProblem(f"{where}.nom", "nom_double", item.name))
        if not item.columns:
            # Un index sans colonne n'indexe rien : c'est une déclaration inachevée.
            problems.append(StorageProblem(f"{where}.colonnes", "index_sans_colonne", item.name))
        if len(item.columns) > MAX_COLUMNS:
            problems.append(
                StorageProblem(f"{where}.colonnes", "trop_de_colonnes", str(len(item.columns)))
            )
        for place, column in enumerate(item.columns):
            if property_keys(column) is None:
                problems.append(
                    StorageProblem(
                        f"{where}.colonnes[{place}]", "chemin_de_propriete_attendu", column
                    )
                )
            elif item.columns.count(column) > 1:
                # La même colonne deux fois dans un index : la seconde n'apporte rien.
                problems.append(
                    StorageProblem(f"{where}.colonnes[{place}]", "colonne_doublee", column)
                )
    return problems
