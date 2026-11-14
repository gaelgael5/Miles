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
from miles.workflowevents.dsl import FragmentError, scope_of
from miles.workflowevents.dsl import parse as parse_fragment
from miles.workflowevents.layout import visible as event_visible
from miles.workflowevents.schema import dedup_problems, payload_problems
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

    Ne couvre que ce qui est instruit à ce jour — arborescence, modèles, types d'event,
    contrats. Chaque
    nouvel objet du paramétrage (mappings, écrans…) ajoute ici sa vérification : une
    version ne fige qu'un état qui passe toutes les règles (story 94b06105, critère 3).
    """
    paths = await copy.paths()
    reports: list[FileReport] = []
    tree = _tree_problems(paths, await copy.read(MANIFEST))
    if tree:
        reports.append(FileReport("", tree))
    entries = [e for e in map(entry_of, paths) if e is not None]
    # Lu AVANT les modèles : un modèle qu'un `DEFINE EVENT` désigne n'est pas soumis à la
    # même règle de vacuité, et c'est l'artefact qui le dit.
    types = await _declared_types(copy, paths)
    for entry in entries:
        problems = await _model_problems(copy, entries, entry, types.models)
        if problems:
            reports.append(FileReport(entry.path, problems))
    for path in paths:
        problems = await _fragment_problems(copy, entries, path, types.twice)
        if problems:
            reports.append(FileReport(path, problems))
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


@dataclass(frozen=True)
class _DeclaredTypes:
    """Ce que les artefacts de tous les périmètres déclarent, vu d'ensemble."""

    # (portée, nom) des modèles qu'un `DEFINE EVENT` désigne.
    models: frozenset[tuple[str, str]]
    # Les noms déclarés par PLUSIEURS périmètres. Un script qui `INCLUDE` les deux
    # artefacts ne charge alors pas du tout — le moteur lève « event 'x' is already
    # declared » (mesuré le 14/11/2026). Vu d'ensemble parce qu'aucun des deux fichiers
    # n'est fautif seul : c'est leur coexistence qui l'est.
    twice: frozenset[str]


async def _declared_types(copy: WorkCopy, paths: list[str]) -> _DeclaredTypes:
    models: set[tuple[str, str]] = set()
    seen: set[str] = set()
    twice: set[str] = set()
    for path in paths:
        if scope_of(path) is None:
            continue
        try:
            declared = parse_fragment(await copy.read(path) or "")
        except FragmentError:
            # L'artefact rapporte lui-même son illisibilité sous son propre chemin.
            continue
        for item in declared:
            models.add(item.model)
            if item.name in seen:
                twice.add(item.name)
            seen.add(item.name)
    return _DeclaredTypes(frozenset(models), frozenset(twice))


async def _model_problems(
    copy: WorkCopy,
    entries: list[ModelEntry],
    entry: ModelEntry,
    declared: frozenset[tuple[str, str]],
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
    if schema.empty and (entry.scope, entry.name) not in declared:
        # Brouillon admis à l'écriture, pas dans une version : un modèle sans propriété
        # ne décrit rien qu'un terminal puisse recevoir (Gael, 23/10/2026).
        #
        # SAUF s'il est le payload d'un type d'event, et c'est une DÉCISION : un
        # `DEFINE EVENT` peut n'apporter que le socle commun — un nom, un `ExternalId`,
        # une date — et déclencher une transition sur ce seul fait. Refuser ici
        # empêcherait de figer un référentiel parfaitement légitime, et c'était déjà
        # l'exception des events avant qu'ils ne deviennent des modèles.
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


async def _fragment_problems(
    copy: WorkCopy, models: list[ModelEntry], path: str, twice: frozenset[str]
) -> tuple[Problem, ...]:
    """Manquements de l'artefact qui déclare les types d'event d'un périmètre.

    C'est ici, et non à l'enregistrement d'un modèle, que se tient la cohérence entre une
    déclaration et le modèle qu'elle désigne : un modèle ne sait pas qui le déclare, et
    lui faire porter la contrainte du moteur l'imposerait à tous les modèles, dont ceux
    qu'aucun `DEFINE EVENT` ne nomme. Une version ne fige donc pas un état où un type
    d'event désigne un modèle disparu, invisible de son périmètre, ou fermé — trois
    états où le moteur refuserait tous les payloads sans qu'aucun fichier paraisse faux.
    """
    scope = scope_of(path)
    if scope is None:
        return ()
    try:
        declared = parse_fragment(await copy.read(path) or "")
    except FragmentError as exc:
        return tuple(
            Problem("", "artefact_illisible", f"ligne {p.line}, colonne {p.column} : {p.message}")
            for p in exc.problems
        )
    known = {(m.scope, m.name): m for m in models}
    problems: list[Problem] = []
    for item in declared:
        where = f"events.{item.name}"
        if item.name in twice:
            problems.append(Problem(where, "nom_declare_deux_fois", item.name))
        if item.model not in known or not event_visible(scope, item.model):
            problems.append(Problem(where, "modele_inconnu", "/".join(item.model)))
            continue
        text = await copy.read(known[item.model].path) or ""
        try:
            schema = parse_schema(text)
        except (ModelSyntaxError, ModelGrammarError):
            # Le modèle rapporte ses propres manquements sous SON chemin : les répéter ici
            # ferait lire deux défauts là où il n'y en a qu'un.
            continue
        problems += [
            Problem(f"{where}.{p.path}", p.code, p.detail)
            for p in payload_problems(text, schema) + dedup_problems(item.unique, schema)
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
