from __future__ import annotations

from typing import Any

from miles_socle.transform.jpath import property_keys

from miles.datamodels.grammar import load_yaml
from miles.datamodels.layout import MODEL_RE, model_path
from miles.datamodels.navigate import kind_at
from miles.datamodels.schema import parse_schema
from miles.git.workcopy import WorkCopy
from miles.storages.layout import Expiry, StorageDoc, StorageProblem

# Ce qu'une clé ou une colonne d'index peut désigner : une valeur, jamais un conteneur.
# Pour l'index, c'est le fondement du mécanisme — une valeur unique par objet et par
# colonne donne une ligne d'index unique, et un tableau la casserait. Pour la clé, un
# conteneur ne se compare pas d'une écriture à l'autre.
_CONTAINERS = {"array": "tableau_interdit", "object": "valeur_attendue"}
# Le seul type sur lequel une règle de péremption se compare (Gael, 09/11/2026). La
# colonne projetée d'une date reste `text` à dessein — `format: date-time` est une
# annotation JSON Schema, pas une garantie —, et c'est l'ordre lexicographique d'un
# ISO-8601 qui tient la comparaison. Un `integer` ou un `boolean`, lui, ne porte aucune
# date : accepter la règle dessus la rendrait inerte au mieux, fausse au pire, alors
# qu'elle désigne des suppressions.
_DATE_KIND = "string"


async def branch_problems(copy: WorkCopy, doc: StorageDoc) -> list[StorageProblem]:
    """Ce que la déclaration exige de la branche : le modèle, et ce que ses jpath désignent."""
    match = MODEL_RE.match(doc.model)
    if match is None or await _schema(copy, doc.model) is None:
        return [StorageProblem("modele", "modele_inconnu", doc.model)]
    root = load_yaml(await copy.read(model_path(match["scope"], match["name"])) or "{}")
    problems = []
    for rank, key in enumerate(doc.keys):
        problems += await _path_problems(copy, match["scope"], root, f"cle[{rank}]", key)
    for rank, item in enumerate(doc.indexes):
        for place, column in enumerate(item.columns):
            where = f"index[{rank}].colonnes[{place}]"
            problems += await _path_problems(copy, match["scope"], root, where, column)
    for rank, rule in enumerate(doc.expiries):
        problems += await _expiry_kind_problems(copy, match["scope"], root, rank, rule)
    return problems


async def _expiry_kind_problems(
    copy: WorkCopy, scope: str, root: Any, rank: int, rule: Expiry
) -> list[StorageProblem]:
    """Le TYPE de la propriété d'une règle de péremption : il demande le modèle.

    La propriété est forcément une colonne d'index déclarée — `form_problems` l'exige, et
    il passe avant —, donc son existence et son caractère scalaire sont déjà vérifiés
    au-dessus. Ce qui reste à dire ici, c'est qu'une date ne se lit pas sur un entier.
    """
    keys = property_keys(rule.property)
    if keys is None:
        return []
    kind = await kind_at(copy.read, scope, root, keys)
    # `None` : la propriété est inconnue du modèle, et la boucle des index l'a déjà dit.
    # Le répéter ici enverrait corriger deux fois la même chose.
    if kind is None or kind == _DATE_KIND:
        return []
    return [StorageProblem(f"peremption[{rank}].propriete", "date_attendue", rule.property)]


async def _schema(copy: WorkCopy, model: str) -> dict[str, Any] | None:
    match = MODEL_RE.match(model)
    if match is None:
        return None
    text = await copy.read(model_path(match["scope"], match["name"]))
    if text is None:
        return None
    try:
        return parse_schema(text).properties
    except ValueError:
        return None


async def _path_problems(
    copy: WorkCopy, scope: str, root: Any, where: str, jpath: str
) -> list[StorageProblem]:
    keys = property_keys(jpath)
    if keys is None:
        return [StorageProblem(where, "chemin_de_propriete_attendu", jpath)]
    kind = await kind_at(copy.read, scope, root, keys)
    if kind is None:
        return [StorageProblem(where, "propriete_inconnue", jpath)]
    code = _CONTAINERS.get(kind)
    return [StorageProblem(where, code, jpath)] if code is not None else []
