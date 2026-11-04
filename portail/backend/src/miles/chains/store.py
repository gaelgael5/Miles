"""La chaîne telle qu'elle vit dans la copie de travail : sa forme, son écriture, sa relecture.

À part du service (01/11/2026) : le service orchestre et journalise, ce module-ci ne
connaît que la copie de travail. La séparation est aussi ce qui garde les deux fichiers
sous la limite de 300 lignes du dépôt.
"""

from __future__ import annotations

from dataclasses import dataclass

from miles.chains.conformance import Divergence, ast_of, divergences
from miles.chains.layout import (
    CHAIN_FILE,
    ChainDoc,
    chain_dir,
    chain_path,
    chain_text,
    files_of,
    read_chain,
    template_path,
)
from miles.datamodels.schema import target_of
from miles.git.workcopy import WorkCopy
from miles.workspaces.model import WorkspaceInputError


@dataclass(frozen=True)
class StoredStep:
    name: str
    template: str
    target: str | None
    # URI des modèles que l'étape lit et produit (24/10/2026) ; None tant qu'ils ne
    # sont pas choisis. Ils ne changent rien à l'exécution : ils servent à l'écran, qui
    # en tire le gabarit du résultat et ce que l'étape transforme.
    source_model: str | None = None
    destination_model: str | None = None


@dataclass(frozen=True)
class StoredChain:
    slug: str
    label: str
    steps: tuple[StoredStep, ...]


@dataclass(frozen=True)
class CheckedChain:
    """La chaîne, et par étape ce que son template ne tient pas de ce qu'il annonce.

    Les écarts ne sont PAS dans `StoredChain` : rien n'en est écrit dans le dépôt, ils
    se recalculent à chaque lecture. Les porter sur la chaîne stockée en ferait une
    donnée qu'on finirait par croire enregistrée.
    """

    chain: StoredChain
    # Même rang que `chain.steps` : le signe se pose sur l'étape, pas sur la chaîne.
    divergences: tuple[tuple[Divergence, ...], ...]


async def checked(copy: WorkCopy, chain: StoredChain) -> CheckedChain:
    """Confronte chaque template au modèle de destination que son étape annonce.

    À la LECTURE autant qu'à l'enregistrement (Gael, 01/11/2026) : une alerte qui ne
    survit pas au rechargement de l'écran ne se voit qu'une fois, et pas forcément par
    celui qu'elle concerne.
    """
    found = [
        await divergences(copy.read, step.destination_model, ast_of(step.template))
        for step in chain.steps
    ]
    return CheckedChain(chain, tuple(found))


async def write_chain(copy: WorkCopy, doc: ChainDoc, stored: StoredChain) -> None:
    kept = {CHAIN_FILE, *(s.template_file for s in doc.steps)}
    # Les templates d'étapes retirées partent avec l'enchaînement qui ne les cite plus.
    for name in files_of(await copy.paths(), doc.slug):
        if name not in kept:
            await copy.remove(f"{chain_dir(doc.slug)}/{name}")
    await copy.write(chain_path(doc.slug), chain_text(doc))
    for step_doc, step in zip(doc.steps, stored.steps, strict=True):
        await copy.write(template_path(doc.slug, step_doc), step.template)
    await copy.git("add", "-A", "--", chain_dir(doc.slug))


def model_ref(raw: str | None) -> str | None:
    """Le modèle choisi, ou None ; une référence qui ne désigne rien est refusée ici.

    Refusée à l'écriture plutôt qu'à la relecture : une chaîne écrite avec une référence
    cassée deviendrait illisible, et le refus arriverait trop tard pour dire quoi faire.
    """
    value = (raw or "").strip()
    if not value:
        return None
    if target_of(value) is None:
        raise WorkspaceInputError("modele", "inconnu")
    return value


async def stored_chain(copy: WorkCopy, slug: str) -> StoredChain | None:
    doc = read_chain(await copy.read(chain_path(slug)))
    if doc is None or doc.slug != slug:
        return None
    steps = []
    for step in doc.steps:
        template = await copy.read(template_path(slug, step))
        if template is None:
            return None
        steps.append(
            StoredStep(step.name, template, step.target, step.source_model, step.destination_model)
        )
    return StoredChain(doc.slug, doc.label, tuple(steps))
