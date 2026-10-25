from __future__ import annotations

from miles.chains.service import stored_chain
from miles.datamodels.layout import MODEL_RE, model_path
from miles.datamodels.schema import model_id
from miles.git.workcopy import WorkCopy
from miles.sources.layout import Entry, SourceDoc, SourceProblem
from miles.storages.layout import read_storage, storage_path
from miles.transform.chain import ChainInvalidError, StepSpec, compile_chain


async def branch_problems(copy: WorkCopy, doc: SourceDoc) -> list[SourceProblem]:
    """Ce que la déclaration exige de la branche : la donnée cible, et chaque entrée."""
    storage = read_storage(await copy.read(storage_path(doc.storage)))
    problems = []
    if storage is None or storage.name != doc.storage:
        problems.append(SourceProblem("storage", "storage_inconnu", doc.storage))
    # Le modèle du storage est la destination attendue de la chaîne : sans lui, on ne
    # peut pas vérifier le raccord, et on ne l'invente pas.
    target = storage.model if storage is not None else None
    for rank, entry in enumerate(doc.entries):
        problems += await _entry_problems(copy, rank, entry, target)
    return problems


async def _entry_problems(
    copy: WorkCopy, rank: int, entry: Entry, target: str | None
) -> list[SourceProblem]:
    where = f"entrees[{rank}]"
    problems = await _model_problems(copy, f"{where}.modele_source", entry.source_model)
    problems += await _chain_problems(copy, where, entry, target)
    return problems


async def _model_problems(copy: WorkCopy, where: str, model: str) -> list[SourceProblem]:
    match = MODEL_RE.match(model)
    if match is None or await copy.read(model_path(match["scope"], match["name"])) is None:
        return [SourceProblem(where, "modele_inconnu", model)]
    return []


async def _chain_problems(
    copy: WorkCopy, where: str, entry: Entry, target: str | None
) -> list[SourceProblem]:
    field = f"{where}.chaine"
    stored = await stored_chain(copy, entry.chain)
    if stored is None:
        return [SourceProblem(field, "chaine_inconnue", entry.chain)]
    try:
        compile_chain([StepSpec(s.template, s.target) for s in stored.steps])
    except ChainInvalidError as exc:
        return [
            SourceProblem(field, "chaine_invalide", f"étape {p.step + 1} : {p.code}")
            for p in exc.problems
        ]
    if not stored.steps:
        return [SourceProblem(field, "chaine_sans_etape", entry.chain)]
    return _endpoints(field, entry, stored.steps[0], stored.steps[-1], target)


def _endpoints(
    field: str, entry: Entry, first: object, last: object, target: str | None
) -> list[SourceProblem]:
    """La chaîne doit partir du modèle source et arriver au modèle du storage.

    Posé par Gael le 25/10/2026 : « une chaine de transformation qui traite de la
    transformation du model source sur la premiere step […] jusqu'a la transformation
    vers le model sur la derniere step ». On ne vérifie que ce que les étapes DÉCLARENT :
    les modèles d'étape sont facultatifs, et une chaîne écrite avant le 24/10 n'en porte
    aucun. Une absence ne se transforme pas en reproche ; une contradiction, si.
    """
    problems = []
    declared_start = getattr(first, "source_model", None)
    expected_start = _uri(entry.source_model)
    if (
        declared_start is not None
        and expected_start is not None
        and declared_start != expected_start
    ):
        problems.append(SourceProblem(field, "chaine_part_d_ailleurs", declared_start))
    declared_end = getattr(last, "destination_model", None)
    expected_end = _uri(target) if target is not None else None
    if declared_end is not None and expected_end is not None and declared_end != expected_end:
        problems.append(SourceProblem(field, "chaine_arrive_ailleurs", declared_end))
    return problems


def _uri(reference: str) -> str | None:
    match = MODEL_RE.match(reference)
    return None if match is None else model_id(match["scope"], match["name"])
