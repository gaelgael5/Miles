from __future__ import annotations

from miles.chains.layout import CHAIN_FILE, chain_dir, chain_path, files_of, read_chain, slugs_in
from miles.datamodels.grammar import Problem
from miles.git.workcopy import WorkCopy
from miles.transform.chain import ChainInvalidError, StepSpec, compile_chain


async def chain_reports(copy: WorkCopy, paths: list[str]) -> list[tuple[str, tuple[Problem, ...]]]:
    """Chaque chaîne de la branche : enchaînement lisible, templates présents et valides.

    Une chaîne retouchée hors de Miles (dans GitHub) ne doit pas être figée en version
    si elle ne passerait plus la vérification qu'impose l'écriture par Miles.
    Rend (chemin de l'enchaînement, problèmes) pour chaque chaîne en défaut.
    """
    reports = []
    for slug in slugs_in(paths):
        problems = await _problems(copy, paths, slug)
        if problems:
            reports.append((chain_path(slug), problems))
    return reports


async def _problems(copy: WorkCopy, paths: list[str], slug: str) -> tuple[Problem, ...]:
    doc = read_chain(await copy.read(chain_path(slug)))
    if doc is None or doc.slug != slug:
        return (Problem("", "enchainement_invalide"),)
    expected = {CHAIN_FILE, *(s.template_file for s in doc.steps)}
    problems = [
        Problem(name, "fichier_de_chaine_inattendu")
        for name in files_of(paths, slug)
        if name not in expected
    ]
    specs = []
    for step in doc.steps:
        template = await copy.read(f"{chain_dir(slug)}/{step.template_file}")
        if template is None:
            problems.append(Problem(step.template_file, "template_absent"))
            continue
        specs.append(StepSpec(template, step.target))
    if len(specs) == len(doc.steps):
        try:
            compile_chain(specs)
        except ChainInvalidError as exc:
            problems += [
                Problem(doc.steps[p.step].name, p.code, p.detail or _first(p)) for p in exc.problems
            ]
    return tuple(problems)


def _first(problem: object) -> str | None:
    violations = getattr(problem, "violations", ())
    return violations[0].construct if violations else None
