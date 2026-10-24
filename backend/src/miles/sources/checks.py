from __future__ import annotations

from miles.chains.service import stored_chain
from miles.git.workcopy import WorkCopy
from miles.sources.layout import SourceDoc, SourceProblem
from miles.storages.layout import read_storage, storage_path
from miles.transform.chain import ChainInvalidError, StepSpec, compile_chain


async def branch_problems(copy: WorkCopy, doc: SourceDoc) -> list[SourceProblem]:
    """Ce que la déclaration exige de la branche : le storage visé, et la chaîne.

    Le modèle et les propriétés filtrables ne sont plus vérifiés ici : ils ont quitté la
    source pour le storage (story 844f15ad), qui les valide à sa propre déclaration.
    """
    problems = await _storage_problems(copy, doc.storage)
    problems += await _chain_problems(copy, doc.chain)
    return problems


async def _storage_problems(copy: WorkCopy, name: str) -> list[SourceProblem]:
    doc = read_storage(await copy.read(storage_path(name)))
    if doc is None or doc.name != name:
        return [SourceProblem("storage", "storage_inconnu", name)]
    return []


async def _chain_problems(copy: WorkCopy, slug: str) -> list[SourceProblem]:
    stored = await stored_chain(copy, slug)
    if stored is None:
        return [SourceProblem("chaine", "chaine_inconnue", slug)]
    try:
        compile_chain([StepSpec(s.template, s.target) for s in stored.steps])
    except ChainInvalidError as exc:
        return [
            SourceProblem("chaine", "chaine_invalide", f"étape {p.step + 1} : {p.code}")
            for p in exc.problems
        ]
    return []
