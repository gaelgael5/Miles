from __future__ import annotations

import re
from dataclasses import dataclass

from miles.contracts.openapi import (
    ContractInvalidError,
    ContractSyntaxError,
    UnsupportedVersionError,
    parse_contract,
)
from miles.contracts.service import read_meta
from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError, Problem, parse_model
from miles.datamodels.service import ModelEntry, entry_of, visible_from
from miles.git.workcopy import WorkCopy
from miles.git.worktree import MANIFEST, diagnose

_CONTRACT_FILE_RE = re.compile(r"^contracts/(?P<slug>[^/]+)/(?P<file>[^/]+)$")
_VERSION_FILE_RE = re.compile(r"^v\d+\.yaml$")


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
        problems = await _contract_problems(copy, path)
        if problems:
            reports.append(FileReport(path, problems))
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
        model = parse_model(text)
    except ModelSyntaxError as exc:
        where = f"ligne {exc.line}, colonne {exc.column}" if exc.line else None
        return (Problem("", "yaml_invalide", where),)
    except ModelGrammarError as exc:
        return tuple(exc.problems)
    problems = []
    # Retouché hors de Miles, un fichier peut ne plus porter le nom de son emplacement :
    # les références, qui se font par nom, ne le retrouveraient plus.
    if model.name != entry.name:
        problems.append(Problem("nom", "nom_different_du_fichier", entry.name))
    visible = visible_from(entries, entry.scope)
    problems += [
        Problem(path, "modele_inconnu", target)
        for path, target in model.references
        if target not in visible
    ]
    return tuple(problems)


async def _contract_problems(copy: WorkCopy, path: str) -> tuple[Problem, ...]:
    match = _CONTRACT_FILE_RE.match(path)
    if match is None or match["file"] == ".gitkeep":
        return ()
    text = await copy.read(path)
    if match["file"] == "contract.yaml":
        meta = read_meta(text)
        if meta is None:
            return (Problem("", "metadonnees_de_contrat_invalides"),)
        if meta[0] != match["slug"]:
            return (Problem("slug", "slug_different_du_dossier", match["slug"]),)
        return ()
    if not _VERSION_FILE_RE.match(match["file"]):
        return (Problem("", "fichier_de_contrat_inattendu"),)
    try:
        parse_contract(text or "")
    except ContractSyntaxError as exc:
        return (Problem("", "openapi_illisible", f"ligne {exc.line}, colonne {exc.column}"),)
    except UnsupportedVersionError as exc:
        return (Problem("openapi", "version_non_prise_en_charge", str(exc.found)),)
    except ContractInvalidError as exc:
        return tuple(Problem(p.path, "openapi_invalide", p.message) for p in exc.problems)
    return ()
