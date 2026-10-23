from __future__ import annotations

from typing import Any

from miles.chains.service import stored_chain
from miles.datamodels.grammar import load_yaml
from miles.datamodels.layout import model_path
from miles.datamodels.navigate import kind_at
from miles.datamodels.schema import parse_schema
from miles.git.workcopy import WorkCopy
from miles.sources.layout import MODEL_RE, SourceDoc, SourceProblem, path_keys
from miles.transform.chain import ChainInvalidError, StepSpec, compile_chain


async def branch_problems(copy: WorkCopy, doc: SourceDoc) -> list[SourceProblem]:
    """Ce que la déclaration exige de la branche : modèle, chaîne, propriétés filtrables."""
    problems: list[SourceProblem] = []
    paths = await copy.paths()
    properties = await _model_properties(copy, doc.model)
    if properties is None:
        problems.append(SourceProblem("modele", "modele_inconnu", doc.model))
    else:
        problems += await _filterable_problems(copy, paths, doc, properties)
    problems += await _chain_problems(copy, doc.chain)
    return problems


async def _model_properties(copy: WorkCopy, model: str) -> dict[str, Any] | None:
    match = MODEL_RE.match(model)
    if match is None:
        return None
    return await _properties_at(copy, model_path(match["scope"], match["name"]))


async def _properties_at(copy: WorkCopy, path: str) -> dict[str, Any] | None:
    text = await copy.read(path)
    if text is None:
        return None
    try:
        return parse_schema(text).properties
    except ValueError:
        return None


async def _filterable_problems(
    copy: WorkCopy, paths: list[str], doc: SourceDoc, properties: dict[str, Any]
) -> list[SourceProblem]:
    match = MODEL_RE.match(doc.model)
    if match is None:
        return []
    root = load_yaml(await copy.read(model_path(match["scope"], match["name"])) or "{}")
    problems = []
    for rank, item in enumerate(doc.filterables):
        where = f"filtrables[{rank}].jpath"
        keys = path_keys(item.jpath)
        if keys is None or any(isinstance(k, int) for k in keys):
            problems.append(SourceProblem(where, "chemin_de_propriete_attendu", item.jpath))
            continue
        kind = await kind_at(copy.read, match["scope"], root, [str(k) for k in keys])
        if kind is None:
            problems.append(SourceProblem(where, "propriete_inconnue", item.jpath))
        elif kind == "array":
            # Une valeur par couple (objet, propriété), donc une ligne d'index unique :
            # c'est le fondement de l'index, et un tableau le casserait.
            problems.append(SourceProblem(where, "tableau_interdit", item.jpath))
        elif kind == "object":
            problems.append(SourceProblem(where, "valeur_attendue", item.jpath))
    return problems


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
