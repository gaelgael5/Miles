"""Lire les storages de la version servie, et les résoudre contre leurs modèles.

Entre la déclaration (`storages/accounts.yaml`) et la table, il manque une chose que la
déclaration ne porte pas : le TYPE de chaque propriété indexable. Il est dans le modèle,
et c'est ici qu'on va le chercher — avec la même marche de schéma que celle qui a montré
l'arbre des propriétés à qui a choisi la colonne. Deux lectures de schéma auraient fini
par nommer le même type autrement, et la colonne aurait cessé de correspondre à ce que
l'écran promettait.

**Rien n'est deviné.** Une colonne qui ne correspond à aucun chemin du modèle n'est pas
posée en `text` « au cas où » : elle fait refuser le storage, nommément. C'est le même
défaut que Gael a rencontré le 01/11/2026 côté portail — un index déclaré sur une
propriété disparue du modèle —, et il ne doit pas se traduire ici par une colonne muette.
"""

from __future__ import annotations

from typing import Any

from miles_socle.parametrage.layout import MODEL_RE, model_path
from miles_socle.parametrage.models import ModelUsage, PathEntry, paths_of, usage_of
from miles_socle.parametrage.refs import ReadFile, inline_refs
from miles_socle.parametrage.storages import (
    MAX_COLUMNS,
    ROOT,
    StorageDoc,
    names_in,
    read_storage,
    storage_path,
)
from miles_socle.parametrage.yaml_read import ParametrageSyntaxError, load_yaml

from environnement.storages.ddl import IDENTIFIER_RE, column_of, sql_type_of
from environnement.storages.model import (
    FIXED_NAMES,
    REFUSAL_BAD_MODEL,
    REFUSAL_BAD_NAME,
    REFUSAL_COLUMN_CLASH,
    REFUSAL_INDEX_NAME,
    REFUSAL_MODEL_MISSING,
    REFUSAL_NOT_SCALAR,
    REFUSAL_TOO_MANY_COLUMNS,
    REFUSAL_UNKNOWN_PROPERTY,
    REFUSAL_UNREADABLE,
    Projection,
    StorageRefusal,
    StorageTable,
    TableIndex,
)


class Declared:
    """Ce que la version servie déclare : les tables à poser, et ce qu'on refuse.

    Les deux ensemble, et jamais l'un sans l'autre : un refus silencieux laisserait
    croire qu'un storage n'était pas déclaré, alors qu'il l'était et qu'il est fautif.
    """

    def __init__(self, tables: list[StorageTable], refusals: list[StorageRefusal]) -> None:
        self.tables, self.refusals = tables, refusals


async def file_declared(read: ReadFile, paths: list[str]) -> Declared:
    """Résout tous les storages que ces chemins désignent, dans l'ordre de leur nom."""
    tables: list[StorageTable] = []
    refusals: list[StorageRefusal] = []
    for name in names_in(paths):
        resolved = await _one(read, name)
        if isinstance(resolved, StorageRefusal):
            refusals.append(resolved)
        else:
            tables.append(resolved)
    return Declared(tables, refusals)


async def _one(read: ReadFile, name: str) -> StorageTable | StorageRefusal:
    doc = read_storage(await read(storage_path(name)))
    if doc is None:
        return StorageRefusal(name, REFUSAL_UNREADABLE, f"{ROOT}/{name}.yaml")
    if doc.name != name or not IDENTIFIER_RE.match(name):
        # Le fichier et la déclaration doivent dire le même nom : la table porte celui du
        # storage, et deux noms en désaccord rendraient indécidable lequel elle porte.
        return StorageRefusal(name, REFUSAL_BAD_NAME, doc.name)
    designation = MODEL_RE.match(doc.model)
    if designation is None:
        return StorageRefusal(name, REFUSAL_BAD_MODEL, doc.model)
    scope, model = designation["scope"], designation["name"]
    if not IDENTIFIER_RE.match(scope):
        # Le schéma PostgreSQL porte le nom du domaine : il doit en être un.
        return StorageRefusal(name, REFUSAL_BAD_MODEL, scope)
    schema = await file_model_schema(read, scope, model)
    if schema is None:
        return StorageRefusal(name, REFUSAL_MODEL_MISSING, doc.model)
    return _resolved(doc, scope, paths_of(schema), usage_of(schema))


async def file_model_schema(read: ReadFile, scope: str, model: str) -> Any | None:
    """Le schéma du modèle, renvois vers d'autres modèles résolus.

    Résolus, et c'est nécessaire : une propriété indexable peut vivre sous un renvoi, et
    le portail l'a proposée parce qu'il résout les mêmes.

    **Public depuis le 03/11/2026** : l'ingestion valide l'objet transformé contre ce
    MÊME schéma résolu (story `d680e811`). Une seconde lecture aurait pu résoudre
    autrement, et la validation aurait alors accepté ou refusé sur une forme que les
    colonnes de la table ne décrivent pas.
    """
    content = await read(model_path(scope, model))
    if content is None:
        return None
    try:
        return await inline_refs(read, load_yaml(content), (scope, model))
    except ParametrageSyntaxError:
        return None


def _resolved(
    doc: StorageDoc, scope: str, offered: list[PathEntry], usage: ModelUsage
) -> StorageTable | StorageRefusal:
    """La table d'une déclaration dont le modèle est lu : une colonne par propriété."""
    by_path = {entry.path: entry for entry in offered}
    projections: dict[str, Projection] = {}
    indexes: list[TableIndex] = []
    # Les colonnes que le MODÈLE déclare, d'abord et dans son ordre : c'est lui qui dit
    # ce que le tableau des objets montre (Gael, 05/11/2026), et la page du modèle les y
    # a cochées. Les colonnes d'index viennent ensuite : une propriété indexée doit être
    # projetée pour être indexable, qu'on la montre ou non.
    for path in usage.columns:
        held = _hold(projections, _projection(path, by_path))
        if isinstance(held, StorageRefusal):
            return StorageRefusal(doc.name, held.code, held.detail)
    for item in doc.indexes:
        if not IDENTIFIER_RE.match(item.name):
            return StorageRefusal(doc.name, REFUSAL_INDEX_NAME, item.name)
        if not item.columns or len(item.columns) > MAX_COLUMNS:
            return StorageRefusal(doc.name, REFUSAL_TOO_MANY_COLUMNS, item.name)
        columns: list[str] = []
        for path in item.columns:
            projected = _hold(projections, _projection(path, by_path))
            if isinstance(projected, StorageRefusal):
                return StorageRefusal(doc.name, projected.code, projected.detail)
            columns.append(projected.column)
        indexes.append(TableIndex(item.name, tuple(columns)))
    return StorageTable(
        storage=doc.name,
        label=doc.label,
        schema=scope,
        table=doc.name,
        model=doc.model,
        projections=tuple(projections.values()),
        indexes=tuple(indexes),
        # La clé déclarée par le MODÈLE l'emporte ; celle du storage reste pour les
        # déclarations qui précèdent cet écran. Changer la clé d'un storage déjà rempli
        # change la forme de `cle` : les objets déjà là gardent l'ancienne, et un import
        # suivant les écrira à neuf au lieu de les mettre à jour.
        keys=usage.key or doc.keys,
    )


def _hold(
    projections: dict[str, Projection], projected: Projection | StorageRefusal
) -> Projection | StorageRefusal:
    """Retient la colonne, ou dit pourquoi on ne peut pas la poser."""
    if isinstance(projected, StorageRefusal):
        return projected
    held = projections.get(projected.column)
    if held is not None and held.keys != projected.keys:
        # Deux chemins qui se réduisent au même nom de colonne. On refuse plutôt que
        # d'inventer un suffixe : personne ne pourrait relier « contact_phone_2 » à son
        # chemin, et le filtre porterait sur une colonne qu'on ne nomme pas.
        return StorageRefusal("", REFUSAL_COLUMN_CLASH, projected.column)
    projections[projected.column] = projected
    return projected


def _projection(path: str, offered: dict[str, PathEntry]) -> Projection | StorageRefusal:
    entry = offered.get(path)
    if entry is None or entry.keys is None:
        # Absente du modèle, ou atteinte à travers un tableau : dans les deux cas il
        # n'existe aucun chemin jsonb scalaire qui y mène, donc aucune colonne possible.
        code = REFUSAL_UNKNOWN_PROPERTY if entry is None else REFUSAL_NOT_SCALAR
        return StorageRefusal("", code, path)
    sql_type = sql_type_of(entry.kind)
    if sql_type is None:
        return StorageRefusal("", REFUSAL_NOT_SCALAR, path)
    column = column_of(entry.keys)
    if not column:
        return StorageRefusal("", REFUSAL_COLUMN_CLASH, path)
    if column in FIXED_NAMES:
        # Une propriété dont le nom dérivé est celui d'une colonne fixe — `$.Id` est le
        # cas courant, et c'est la première qu'on veut montrer. On la préfixe plutôt que
        # de refuser le storage : le nom de colonne est INTERNE (les écrans nomment la
        # propriété par son chemin déclaré), donc le préfixe ne se lit nulle part, alors
        # qu'un refus rendrait le storage entier invisible. Si deux chemins se réduisent
        # malgré tout au même nom, la règle d'ambiguïté ci-dessous tranche, nommément.
        column = f"prop_{column}"
    return Projection(column=column, keys=entry.keys, kind=entry.kind, sql_type=sql_type)
