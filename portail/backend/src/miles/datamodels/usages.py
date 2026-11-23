"""À quoi sert un modèle : ce qui le DÉSIGNE dans la branche, et ce qui ne le trouve plus.

Jusqu'au 14/11/2026, c'est le RANGEMENT qui disait le rôle : un schéma d'event vivait sous
`shared/events/`, un modèle d'objet sous `shared/models/`. Depuis que « ce qui fait d'un
modèle un type d'event, c'est qu'un `DEFINE EVENT` le nomme, et rien d'autre » (story
`d781001a`), les deux sont dans le même dossier — et la liste des modèles les rend
identiques. Gael, le 16/11/2026 : « la façon d'identifier qui fait quoi m'échappe. »

Le rôle se LIT donc des déclarations qui désignent le modèle, et de rien d'autre : ni de
son nom, ni de son emplacement. C'est interdit par la story `e36192f8`, et pour la raison
qui a fait retirer la séparation — le registre du moteur résout `AS @…` depuis les
modèles, sans égard pour les dossiers.

UNE SEULE passe, dans la copie que l'appelant tient déjà, sur les chemins qu'il a déjà
listés : la page des modèles est sur le chemin critique mesuré de l'enabler `7fb3577c`, et
un geste de branche par rubrique lui aurait coûté quatre ouvertures de plus.

Ce module ne REFUSE rien. Une désignation dont la cible manque est RENDUE, pour qu'elle se
voie à l'écran au lieu de n'apparaître qu'au blocage d'une version ; ce qui empêche de
figer reste dit par `miles.workshop.validation`, seul arbitre. Deux règles de refus
écrites à deux endroits auraient divergé.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from miles_socle.parametrage.chains import chain_path, read_chain, slugs_in
from miles_socle.parametrage.layout import MODEL_RE, target_of
from miles_socle.parametrage.sources import names_in as source_names
from miles_socle.parametrage.sources import read_source, source_path
from miles_socle.parametrage.storages import names_in as storage_names
from miles_socle.parametrage.storages import read_storage, storage_path

from miles.datamodels.layout import ModelEntry
from miles.datamodels.schema import references_in
from miles.workflowevents.dsl import FragmentError, scope_of
from miles.workflowevents.dsl import parse as parse_fragment

# Lire UN fichier de la branche. Le même contrat que `miles_socle.parametrage.refs` et
# que `kind_at` : ce module ne fait rien d'autre de la copie, et ne pas la prendre en
# entier le rend éprouvable sans dépôt ni forge.
Reader = Callable[[str], Awaitable[str | None]]

# Les natures de désignation. Des constantes et non une énumération : elles voyagent
# telles quelles jusqu'à l'écran, qui en dérive un libellé et un lien — une énumération
# aurait ajouté une traduction sans rien garantir de plus.
EVENT_TYPE = "event_type"
STORAGE = "storage"
SOURCE = "source"
CHAIN_STEP = "chain_step"
MODEL = "model"


@dataclass(frozen=True)
class Designation:
    """Une déclaration, et le modèle qu'elle désigne."""

    kind: str
    # L'identifiant par lequel l'écran OUVRE le désignateur : le nom du type d'event, du
    # storage ou de la source, le slug de la chaîne — et « portée/nom » pour un modèle,
    # dont la rubrique n'est pas plate (voir `_in_models`).
    name: str
    # Son libellé quand la déclaration en porte un ; None sinon.
    label: str | None
    # Le fichier qui porte la déclaration.
    path: str
    target: tuple[str, str]
    # La partie du désignateur qui désigne : l'étape d'une chaîne, le rang d'une entrée
    # de source. None quand le désignateur n'a qu'un seul endroit où désigner.
    part: str | None = None


@dataclass(frozen=True)
class Listed:
    """Un modèle de la liste, avec ce qui le désigne ; aucune désignation n'est une anomalie."""

    entry: ModelEntry
    usages: tuple[Designation, ...]


@dataclass(frozen=True)
class Listing:
    models: tuple[Listed, ...]
    # Désignations dont la cible n'est pas un modèle de la branche.
    broken: tuple[Designation, ...]


async def read_designations(
    read: Reader, paths: list[str], models: Sequence[tuple[ModelEntry, str]]
) -> list[Designation]:
    """Toutes les désignations de la branche — les CINQ natures —, sans doublon.

    Rendue partageable le 23/11/2026 (bug `6ed86d6b`), et c'est le fond de ce bug : DEUX
    lectures répondaient à « qui désigne ce modèle ? » sans que rien ne dise laquelle était
    la bonne. Celle de l'écran connaissait cinq natures, celle du refus de suppression deux
    — un modèle qu'un storage projetait se supprimait. Les faire coïncider par le bas aurait
    caché des désignations réelles ; les laisser diverger aurait voulu entretenir deux
    listes pour toujours. Il y a donc une lecture, et deux appelants :
    `read_listing` ci-dessous, et `datamodels.links.users`, qui REFUSE.

    Ce module, lui, ne refuse toujours rien (voir l'en-tête) : il rend ce qui désigne, y
    compris quand la cible manque. C'est l'appelant qui en tire un refus.
    """
    found = _in_models(models)
    found += await _in_artefacts(read, paths)
    found += await _in_storages(read, paths)
    found += await _in_sources(read, paths)
    found += await _in_chains(read, paths)
    return _without_doubles(found)


async def read_listing(
    read: Reader, paths: list[str], models: Sequence[tuple[ModelEntry, str]]
) -> Listing:
    """La liste des modèles et ce qui les désigne ; `models` porte le texte déjà lu."""
    by_model: dict[tuple[str, str], list[Designation]] = {(e.scope, e.name): [] for e, _ in models}
    broken: list[Designation] = []
    for designation in await read_designations(read, paths, models):
        if designation.target in by_model:
            by_model[designation.target].append(designation)
        else:
            broken.append(designation)
    return Listing(
        tuple(Listed(entry, tuple(by_model[(entry.scope, entry.name)])) for entry, _ in models),
        tuple(broken),
    )


async def read_event_designations(read: Reader, paths: list[str]) -> list[Designation]:
    """Les `DEFINE EVENT … AS @modele` de la branche : qui prend quel modèle pour payload.

    Rendue à part de `read_listing` pour les appelants qui ne veulent QUE cette nature —
    le geste d'un storage ou d'une source, qui refuse de désigner un payload
    (`datamodels.payloads`). Ils n'ouvrent ainsi ni les storages, ni les sources, ni les
    chaînes de la branche, dont ils n'ont rien à faire.
    """
    return await _in_artefacts(read, paths)


def _without_doubles(found: list[Designation]) -> list[Designation]:
    """La même désignation deux fois ne se dit qu'une.

    Cas réel : une étape de chaîne dont le modèle source et le modèle de destination sont
    le même — elle désigne bien ce modèle, mais une seule fois à l'écran.
    """
    seen: dict[Designation, None] = {}
    for designation in found:
        seen.setdefault(designation, None)
    return list(seen)


def _in_models(models: Sequence[tuple[ModelEntry, str]]) -> list[Designation]:
    """Les `$ref` d'un modèle vers un autre."""
    found = []
    for entry, text in models:
        for target in sorted(references_in(text)):
            # Un modèle qui se désigne lui-même (un schéma récursif) n'est pas son propre
            # usage : l'afficher ferait croire qu'il sert à quelque chose d'autre.
            if target != (entry.scope, entry.name):
                # « portée/nom » : c'est sous cette forme que l'écran ouvre un modèle, et
                # le nom seul aurait fait ouvrir le transverse homonyme d'un modèle de
                # domaine. Les autres natures n'ont qu'un nom, leur rubrique étant plate.
                name = f"{entry.scope}/{entry.name}"
                found.append(Designation(MODEL, name, entry.label, entry.path, target))
    return found


async def _in_artefacts(read: Reader, paths: list[str]) -> list[Designation]:
    """Les `DEFINE EVENT … AS @modele` des artefacts de périmètre.

    Le type d'event est nommé, pas seulement l'artefact : c'est le type qu'on cherche
    quand on se demande à quoi sert un modèle (critère 3 de la story `e36192f8`).
    """
    found = []
    for path in paths:
        if scope_of(path) is None:
            continue
        try:
            declared = parse_fragment(await read(path) or "")
        except FragmentError:
            # Illisible (retouché hors de Miles) : on ne devine pas ce qu'il désigne, et
            # on n'invente pas un usage. La validation de la branche le nomme, et c'est
            # elle qui refuse d'en figer une version.
            continue
        found += [Designation(EVENT_TYPE, d.name, d.label, path, d.model) for d in declared]
    return found


async def _in_storages(read: Reader, paths: list[str]) -> list[Designation]:
    found = []
    for name in storage_names(paths):
        path = storage_path(name)
        doc = read_storage(await read(path))
        match = MODEL_RE.match(doc.model) if doc is not None else None
        if doc is None or match is None:
            # Le champ ne désigne pas un modèle : il n'y a pas de cible à rattacher, même
            # cassée. Le storage le dit déjà sur son écran (`modele_inconnu`).
            continue
        target = (match["scope"], match["name"])
        found.append(Designation(STORAGE, name, doc.label, path, target))
    return found


async def _in_sources(read: Reader, paths: list[str]) -> list[Designation]:
    found = []
    for name in source_names(paths):
        path = source_path(name)
        doc = read_source(await read(path))
        if doc is None:
            continue
        for rank, entry in enumerate(doc.entries):
            match = MODEL_RE.match(entry.source_model)
            if match is None:
                continue
            target = (match["scope"], match["name"])
            found.append(Designation(SOURCE, name, doc.label, path, target, f"entrees[{rank}]"))
    return found


async def _in_chains(read: Reader, paths: list[str]) -> list[Designation]:
    """Les modèles qu'une étape de chaîne lit et produit.

    Facultatifs : une chaîne écrite avant le 24/10/2026 n'en porte aucun, et une absence
    ne se transforme pas en usage supposé.
    """
    found = []
    for slug in slugs_in(paths):
        path = chain_path(slug)
        doc = read_chain(await read(path))
        if doc is None:
            continue
        for step in doc.steps:
            for reference in (step.source_model, step.destination_model):
                target = target_of(reference) if reference is not None else None
                if target is None:
                    continue
                found.append(Designation(CHAIN_STEP, slug, doc.label, path, target, step.name))
    return found
