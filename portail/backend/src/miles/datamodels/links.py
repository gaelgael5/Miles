"""Les liens d'un modèle, dans les deux sens, quand ils DÉCIDENT d'une écriture.

Deux questions, et elles commandent deux refus : « ce que ce schéma désigne existe-t-il ? »
(sinon `modele_inconnu`, et rien n'est écrit) et « qui désigne ce modèle ? » (si quelqu'un,
`utilise`, et rien n'est supprimé).

**Ce n'est pas `usages.py`, et la différence est à connaître avant d'unifier les deux.**
`usages.py` REND à l'écran tout ce qui désigne un modèle — cinq natures, dont les storages,
les sources et les étapes de chaîne — et ne refuse rien. Ici, le refus de suppression ne
regarde que deux natures : un autre MODÈLE par un `$ref`, et l'ARTEFACT d'un périmètre par
le `AS @…` d'un `DEFINE EVENT`. Les faire coïncider élargirait le refus à des cas qu'il n'a
jamais couverts : c'est un changement de comportement, pas une factorisation, et il se
décide ailleurs qu'ici.
"""

from __future__ import annotations

from miles.datamodels.grammar import ModelGrammarError, Problem
from miles.datamodels.layout import ModelEntry, entry_of, visible
from miles.datamodels.reading import entries
from miles.datamodels.schema import ModelSchema, references_in
from miles.git.workcopy import WorkCopy
from miles.workflowevents.dsl import FragmentError, scope_of
from miles.workflowevents.dsl import parse as parse_fragment


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

    Deux genres de désignation, et pas un seul : un autre MODÈLE par un `$ref`, et
    l'ARTEFACT d'un périmètre par le `AS @…` d'un `DEFINE EVENT`. Depuis le 14/11/2026,
    c'est le second qui fait d'un modèle un type d'event — sans cette lecture, supprimer
    un modèle laisserait une déclaration qui ne désigne plus rien : la version de la
    branche le refuserait, mais trop tard, après la suppression et depuis un autre écran.
    """
    found = []
    for path in await copy.paths():
        model = entry_of(path)
        if model == target:
            continue
        if model is not None:
            if (target.scope, target.name) in references_in(await copy.read(path) or ""):
                found.append(path)
        elif scope_of(path) is not None and await _declared_in(copy, path, target):
            found.append(path)
    return found


async def _declared_in(copy: WorkCopy, path: str, target: ModelEntry) -> bool:
    """L'artefact d'un périmètre déclare-t-il un type d'event sur `target` ?"""
    try:
        declared = parse_fragment(await copy.read(path) or "")
    except FragmentError:
        # Illisible (retouché hors de Miles) : on ne sait pas ce qu'il désigne, donc on ne
        # bloque pas la suppression sur une supposition. Rien ne se perd pour autant — la
        # validation de la branche refuse de figer une version tant que cet artefact ne se
        # relit pas, et c'est là que le défaut se nomme.
        return False
    return any(d.model == (target.scope, target.name) for d in declared)
