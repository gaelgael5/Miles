from __future__ import annotations

import re
from dataclasses import dataclass

from miles.contracts.derived import STALE, UNDERIVABLE, derived_state
from miles.contracts.layout import META, VERSION_RE, read_meta, versions_in
from miles.contracts.openapi import (
    ContractInvalidError,
    ContractSyntaxError,
    UnsupportedVersionError,
    parse_contract,
)
from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError, Problem
from miles.datamodels.layout import ModelEntry, entry_of, visible
from miles.datamodels.schema import model_id, parse_schema
from miles.git.workcopy import WorkCopy
from miles.git.worktree import MANIFEST, diagnose
from miles.workshop.chain_validation import chain_reports, source_reports, storage_reports

_CONTRACT_FILE_RE = re.compile(r"^contracts/(?P<slug>[^/]+)/(?P<file>[^/]+)$")
_DERIVED_RE = re.compile(r"^contracts/(?P<slug>[^/]+)/models/v(?P<number>\d+)/[^/]+$")


@dataclass(frozen=True)
class FileReport:
    """Manquements d'un fichier ; `path` vide : l'arborescence elle-même."""

    path: str
    problems: tuple[Problem, ...]


async def validate_branch(copy: WorkCopy) -> list[FileReport]:
    """Toutes les règles connues du paramétrage, sur l'état de la copie ; vide : valide.

    Ne couvre que ce qui est instruit à ce jour — arborescence, modèles, contrats. Chaque
    nouvel objet du paramétrage (mappings, écrans…) ajoute ici sa vérification : une
    version ne fige qu'un état qui passe toutes les règles (story 94b06105, critère 3).
    """
    paths = await copy.paths()
    reports: list[FileReport] = []
    tree = _tree_problems(paths, await copy.read(MANIFEST))
    if tree:
        reports.append(FileReport("", tree))
    entries = [e for e in map(entry_of, paths) if e is not None]
    for entry in entries:
        problems = await _model_problems(copy, entries, entry)
        if problems:
            reports.append(FileReport(entry.path, problems))
    for path in paths:
        problems = await _contract_problems(copy, paths, path)
        if problems:
            reports.append(FileReport(path, problems))
    reports += [FileReport(path, problems) for path, problems in await chain_reports(copy, paths)]
    reports += [FileReport(path, problems) for path, problems in await source_reports(copy, paths)]
    reports += [FileReport(path, problems) for path, problems in await storage_reports(copy, paths)]
    return sorted(reports, key=lambda r: r.path)


def _tree_problems(paths: list[str], manifest: str | None) -> tuple[Problem, ...]:
    diagnosis = diagnose(paths, manifest)
    problems = []
    if diagnosis.manifest != "valide":
        problems.append(Problem(MANIFEST, f"manifeste_{diagnosis.manifest}"))
    problems += [Problem(d, "dossier_d_environnement") for d in diagnosis.environment_dirs]
    problems += [Problem(p, "emplacement_inattendu") for p in diagnosis.unexpected]
    return tuple(problems)


async def _model_problems(
    copy: WorkCopy, entries: list[ModelEntry], entry: ModelEntry
) -> tuple[Problem, ...]:
    text = await copy.read(entry.path) or ""
    try:
        schema = parse_schema(text)
    except ModelSyntaxError as exc:
        where = f"ligne {exc.line}, colonne {exc.column}" if exc.line else None
        return (Problem("", "yaml_invalide", where),)
    except ModelGrammarError as exc:
        return tuple(exc.problems)
    problems = []
    if schema.empty:
        # Brouillon admis à l'écriture, pas dans une version : un modèle sans propriété
        # ne décrit rien qu'un terminal puisse recevoir (Gael, 23/10/2026).
        problems.append(Problem("properties", "proprietes_vides"))
    # Retouché hors de Miles, un fichier peut ne plus porter l'`$id` de son emplacement :
    # les références, qui se font par cet URI, ne le retrouveraient plus.
    expected = model_id(entry.scope, entry.name)
    if schema.identifier != expected:
        problems.append(Problem("$id", "id_different_du_fichier", expected))
    known = {(e.scope, e.name) for e in entries}
    problems += [
        Problem(where, "modele_inconnu", f"{scope}/{name}")
        for where, (scope, name) in schema.references
        if (scope, name) not in known or not visible(entry, (scope, name))
    ]
    return tuple(problems)


async def _contract_problems(copy: WorkCopy, paths: list[str], path: str) -> tuple[Problem, ...]:
    derived = _DERIVED_RE.match(path)
    if derived is not None:
        # Un modèle dérivé sans la version dont il vient ne dit plus rien du contrat.
        if int(derived["number"]) not in versions_in(paths, derived["slug"]):
            return (Problem("", "modele_derive_orphelin"),)
        return ()
    match = _CONTRACT_FILE_RE.match(path)
    if match is None or match["file"] == ".gitkeep":
        return ()
    text = await copy.read(path)
    if match["file"] == META:
        meta = read_meta(text)
        if meta is None:
            return (Problem("", "metadonnees_de_contrat_invalides"),)
        if meta.slug != match["slug"]:
            return (Problem("slug", "slug_different_du_dossier", match["slug"]),)
        # Bloquant (Gael, 22/10/2026) : un contrat déclaré mais jamais intégré ne décrit
        # rien, et une version du paramétrage ne fige pas une promesse vide.
        if not versions_in(paths, meta.slug):
            return (Problem("", "contrat_sans_fichier"),)
        return ()
    if not VERSION_RE.match(match["file"]):
        return (Problem("", "fichier_de_contrat_inattendu"),)
    try:
        parsed = parse_contract(text or "")
    except ContractSyntaxError as exc:
        return (Problem("", "openapi_illisible", f"ligne {exc.line}, colonne {exc.column}"),)
    except UnsupportedVersionError as exc:
        return (Problem("openapi", "version_non_prise_en_charge", str(exc.found)),)
    except ContractInvalidError as exc:
        return tuple(Problem(p.path, "openapi_invalide", p.message) for p in exc.problems)
    number = int(match["file"].removeprefix("v").removesuffix(".yaml"))
    state = await derived_state(copy.read, paths, match["slug"], number, parsed.document)
    if state.state == UNDERIVABLE:
        return state.problems
    if state.state == STALE:
        # Absents, en trop ou retouchés : les modèles ne sont plus ce que dit le contrat
        # (story 47f55d8b). « Redériver les modèles » les réécrit d'après le fichier.
        return (Problem("models", "modeles_derives_desynchronises"),)
    return ()
