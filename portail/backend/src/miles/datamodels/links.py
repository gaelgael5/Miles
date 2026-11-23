"""Les liens d'un modèle, dans les deux sens, quand ils DÉCIDENT d'une écriture.

Deux questions, et elles commandent deux refus : « ce que ce schéma désigne existe-t-il ? »
(sinon `modele_inconnu`, et rien n'est écrit) et « qui désigne ce modèle ? » (si quelqu'un,
`utilise`, et rien n'est supprimé).

**Le refus de suppression lit exactement ce que l'écran rend** : les cinq natures de
désignation, par `usages.read_designations`. C'est la correction du bug `6ed86d6b`, le
23/11/2026 — avant, ce module portait sa propre lecture de deux natures, et la divergence
elle-même était le défaut. La répartition reste celle de l'en-tête d'`usages.py` : il REND
ce qui désigne, sans jamais refuser ; le refus, lui, est ici.
"""

from __future__ import annotations

from miles.datamodels.grammar import ModelGrammarError, Problem
from miles.datamodels.layout import ModelEntry, visible
from miles.datamodels.reading import entries, entries_in
from miles.datamodels.schema import ModelSchema
from miles.datamodels.usages import read_designations
from miles.git.workcopy import WorkCopy


async def check_references(copy: WorkCopy, entry: ModelEntry, schema: ModelSchema) -> None:
    """Tous les `$ref` du schéma mènent-ils à un modèle connu et visible d'ici ?"""
    known = {(e.scope, e.name) for e in await entries(copy)} | {(entry.scope, entry.name)}
    missing = [
        Problem(where, "modele_inconnu", f"{scope}/{name}")
        for where, (scope, name) in schema.references
        if (scope, name) not in known or not visible(entry, (scope, name))
    ]
    if missing:
        raise ModelGrammarError(missing)


async def users(copy: WorkCopy, target: ModelEntry) -> list[str]:
    """Documents qui désignent `target` : sa suppression les casserait.

    LES CINQ NATURES depuis le 23/11/2026 (bug `6ed86d6b`), et par la lecture que la liste
    des modèles emploie. Avant, ce refus n'en connaissait que deux — un autre MODÈLE par un
    `$ref`, et l'ARTEFACT d'un périmètre par le `AS @…` d'un `DEFINE EVENT` — si bien que
    supprimer un modèle qu'un storage projetait rendait `204` : le paramétrage devenait
    incohérent, et ça ne se disait qu'à l'ouverture de l'écran de figement, depuis un autre
    écran et après que le commit de suppression était parti. L'argument qui avait fait
    ajouter l'artefact le 14/11/2026 valait mot pour mot pour les trois natures qui
    manquaient.
    """
    paths = await copy.paths()
    # Le TEXTE de chaque modèle, pour ses `$ref` — et rien de plus : un refus nomme des
    # CHEMINS, donc on ne passe pas par `described`, qui lirait en plus les métadonnées de
    # chaque modèle pour un label dont ce refus n'a que faire. Une seule passe de lecture
    # de la branche, comme avant : ce geste ouvrait déjà chaque modèle.
    models = [(entry, await copy.read(entry.path) or "") for entry in entries_in(paths)]
    found: dict[str, None] = {}
    for designation in await read_designations(copy.read, paths, models):
        if designation.target != (target.scope, target.name):
            continue
        # Le fichier du modèle n'est pas son propre usage : un schéma récursif reste
        # supprimable, et c'est déjà ce que faisait la lecture précédente.
        if designation.path == target.path:
            continue
        # Un document qui désigne deux fois (deux entrées d'une source sur le même modèle)
        # n'est nommé qu'une fois : `by` porte des chemins, pas des désignations.
        found.setdefault(designation.path, None)
    return list(found)
