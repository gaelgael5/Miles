"""Écriture d'une déclaration de storage, et son diagnostic à la saisie.

La LECTURE est au socle depuis le 02/11/2026 (`miles_socle.parametrage.storages`) : le
module d'environnement lit les mêmes fichiers dans la version qu'il héberge. Ce qui reste
ici suppose ce que seul le module de paramétrage a — la branche, le registre des modèles,
et le parseur de jpath du moteur.

Les noms réexportés le sont pour les appelants du produit, qui n'ont pas à savoir de quel
côté de la frontière chaque pièce vit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from miles_socle.parametrage.storages import (
    MAX_COLUMNS as MAX_COLUMNS,
)
from miles_socle.parametrage.storages import (
    NAME_RE as NAME_RE,
)
from miles_socle.parametrage.storages import (
    ROOT as ROOT,
)
from miles_socle.parametrage.storages import (
    Index as Index,
)
from miles_socle.parametrage.storages import (
    StorageDoc as StorageDoc,
)
from miles_socle.parametrage.storages import (
    names_in as names_in,
)
from miles_socle.parametrage.storages import (
    read_storage as read_storage,
)
from miles_socle.parametrage.storages import (
    storage_path as storage_path,
)

from miles.datamodels.layout import MODEL_RE
from miles.transform.jpath import property_keys


@dataclass(frozen=True)
class StorageProblem:
    path: str
    code: str
    detail: str | None = None


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
