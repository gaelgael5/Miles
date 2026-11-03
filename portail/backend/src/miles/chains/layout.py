"""Ce que le module de paramétrage fait d'une déclaration de chaîne : l'ÉCRIRE et la
DIAGNOSTIQUER.

La grammaire et la LECTURE sont au socle depuis le 03/11/2026 (`miles_socle.parametrage.chains`,
enabler `b2a215ee`), deuxième usage : le module d'environnement lit les mêmes fichiers dans
la version qu'il héberge, pour appliquer la chaîne qu'une entrée de source nomme. Elles
sont réexportées ici sous leurs noms d'origine — les appelants du portail n'ont pas à
savoir qu'elles ont déménagé.

Ce qui RESTE ici, et pourquoi : l'écriture suppose la forme exacte du fichier qu'on
produit, et le diagnostic suppose le vocabulaire de slug et le refus rendu à un écran. Un
consommateur n'a que faire de l'un ni de l'autre : il lit un fichier déjà écrit, et un
refus se rend à qui édite, pas à qui exécute.
"""

from __future__ import annotations

import json

from miles_socle.parametrage.chains import (
    CHAIN_FILE,
    FORMAT_VERSION,
    MAX_STEPS,
    ROOT,
    STEP_NAME_RE,
    TEMPLATE_SUFFIX,
    ChainDoc,
    StepDoc,
    chain_dir,
    chain_path,
    files_of,
    read_chain,
    slugs_in,
    template_path,
)

from miles.contracts.openapi import SLUG_RE
from miles.workspaces.model import WorkspaceInputError

__all__ = [
    "CHAIN_FILE",
    "FORMAT_VERSION",
    "MAX_STEPS",
    "ROOT",
    "STEP_NAME_RE",
    "TEMPLATE_SUFFIX",
    "ChainDoc",
    "StepDoc",
    "chain_dir",
    "chain_path",
    "chain_text",
    "checked_slug",
    "checked_steps",
    "files_of",
    "read_chain",
    "slugs_in",
    "template_path",
]


def chain_text(doc: ChainDoc) -> str:
    """Enchaînement écrit à l'identique pour une même chaîne : le rejeu ne fait pas de diff."""
    data = {
        "format_version": FORMAT_VERSION,
        "slug": doc.slug,
        "label": doc.label,
        # L'ordre du tableau est l'ordre d'application, choisi par l'utilisateur.
        "steps": [_step_data(s) for s in doc.steps],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _step_data(step: StepDoc) -> dict[str, object]:
    data: dict[str, object] = {
        "name": step.name,
        "template": step.template_file,
        "target": step.target,
    }
    # Omis tant qu'ils ne sont pas renseignés : une chaîne d'avant le 24/10/2026 se
    # réécrit alors à l'identique, et le rejeu ne fait toujours pas de diff.
    if step.source_model is not None:
        data["source_model"] = step.source_model
    if step.destination_model is not None:
        data["destination_model"] = step.destination_model
    return data


def checked_slug(slug: str) -> str:
    slug = slug.strip()
    if not slug:
        raise WorkspaceInputError("slug", "vide")
    if not SLUG_RE.match(slug):
        raise WorkspaceInputError("slug")
    return slug


def checked_steps(steps: list[StepDoc]) -> None:
    if len(steps) > MAX_STEPS:
        raise WorkspaceInputError("steps")
    names = [s.name for s in steps]
    if any(not STEP_NAME_RE.match(n) for n in names) or len(set(names)) != len(names):
        # Un nom d'étape devient un nom de fichier : unique, et sans rien qui sorte du
        # répertoire de la chaîne.
        raise WorkspaceInputError("steps", "nom_d_etape")
