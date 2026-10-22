from __future__ import annotations

from typing import Any

from miles.chains.service import stored_chain
from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError, load_yaml, parse_model
from miles.datamodels.service import entry_of, model_path, visible_from
from miles.git.workcopy import WorkCopy
from miles.sources.layout import MODEL_RE, SourceDoc, SourceProblem, path_keys
from miles.transform.chain import ChainInvalidError, StepSpec, compile_chain

# Bornes de la descente dans les modèles imbriqués : un modèle qui se désigne lui-même
# (personne → parent: personne) ferait boucler la résolution d'un filtre sans elle.
MAX_DEPTH = 16


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
        parse_model(text)
    except (ModelSyntaxError, ModelGrammarError):
        return None
    declared = (load_yaml(text) or {}).get("proprietes") or {}
    return dict(declared)


async def _filterable_problems(
    copy: WorkCopy, paths: list[str], doc: SourceDoc, properties: dict[str, Any]
) -> list[SourceProblem]:
    match = MODEL_RE.match(doc.model)
    scope = match["scope"] if match else "shared"
    visible = visible_from([e for e in map(entry_of, paths) if e is not None], scope)
    problems = []
    for rank, item in enumerate(doc.filterables):
        where = f"filtrables[{rank}].jpath"
        keys = path_keys(item.jpath)
        if keys is None or any(isinstance(k, int) for k in keys):
            problems.append(SourceProblem(where, "chemin_de_propriete_attendu", item.jpath))
            continue
        kind = await _kind(copy, visible, properties, [str(k) for k in keys])
        if kind is None:
            problems.append(SourceProblem(where, "propriete_inconnue", item.jpath))
        elif kind == "liste":
            # Une valeur par couple (objet, propriété), donc une ligne d'index unique :
            # c'est le fondement de l'index, et un tableau le casserait.
            problems.append(SourceProblem(where, "tableau_interdit", item.jpath))
        elif kind == "objet":
            problems.append(SourceProblem(where, "valeur_attendue", item.jpath))
    return problems


async def _kind(
    copy: WorkCopy, visible: dict[str, Any], properties: dict[str, Any], keys: list[str]
) -> str | None:
    """Type de la propriété désignée, en descendant dans les modèles `objet`."""
    current = properties
    for depth, key in enumerate(keys):
        spec = current.get(key)
        if not isinstance(spec, dict) or depth >= MAX_DEPTH:
            return None
        kind = spec.get("type")
        if depth == len(keys) - 1:
            return str(kind)
        target = visible.get(str(spec.get("modele"))) if kind == "objet" else None
        if target is None:
            return None
        nested = await _properties_at(copy, target.path)
        if nested is None:
            return None
        current = nested
    return None


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
