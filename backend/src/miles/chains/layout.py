from __future__ import annotations

import json
import re
from dataclasses import dataclass

from miles.contracts.openapi import SLUG_RE
from miles.workspaces.model import WorkspaceInputError

# Une chaîne par répertoire, nommé d'après son slug (Gael, 22/10/2026) : un fichier JSON
# pour l'enchaînement, un fichier par template. Racine du dépôt, sans niveau domaine.
ROOT = "transformations"
CHAIN_FILE = "chain.json"
FORMAT_VERSION = 1
STEP_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
TEMPLATE_SUFFIX = ".jslt"
MAX_STEPS = 200
_FILE_RE = re.compile(rf"^{ROOT}/(?P<slug>[^/]+)/(?P<file>[^/]+)$")


@dataclass(frozen=True)
class StepDoc:
    name: str
    # Vide : le résultat du template devient le message (story 66ae5c10).
    target: str | None

    @property
    def template_file(self) -> str:
        return f"{self.name}{TEMPLATE_SUFFIX}"


@dataclass(frozen=True)
class ChainDoc:
    slug: str
    label: str
    steps: tuple[StepDoc, ...]


def chain_dir(slug: str) -> str:
    return f"{ROOT}/{slug}"


def chain_path(slug: str) -> str:
    return f"{chain_dir(slug)}/{CHAIN_FILE}"


def template_path(slug: str, step: StepDoc) -> str:
    return f"{chain_dir(slug)}/{step.template_file}"


def chain_text(doc: ChainDoc) -> str:
    """Enchaînement écrit à l'identique pour une même chaîne : le rejeu ne fait pas de diff."""
    data = {
        "format_version": FORMAT_VERSION,
        "slug": doc.slug,
        "label": doc.label,
        # L'ordre du tableau est l'ordre d'application, choisi par l'utilisateur.
        "steps": [
            {"name": s.name, "template": s.template_file, "target": s.target} for s in doc.steps
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def read_chain(text: str | None) -> ChainDoc | None:
    """Enchaînement lu, ou None s'il est absent ou ne respecte pas sa forme."""
    try:
        data = json.loads(text) if text is not None else None
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("format_version") != FORMAT_VERSION:
        return None
    slug, label, steps = data.get("slug"), data.get("label"), data.get("steps")
    if not isinstance(slug, str) or not isinstance(label, str) or not isinstance(steps, list):
        return None
    read = [_step(raw) for raw in steps]
    if any(s is None for s in read):
        return None
    names = [s.name for s in read if s is not None]
    if len(set(names)) != len(names):
        return None
    return ChainDoc(slug, label, tuple(s for s in read if s is not None))


def _step(raw: object) -> StepDoc | None:
    if not isinstance(raw, dict):
        return None
    name, template, target = raw.get("name"), raw.get("template"), raw.get("target")
    if not isinstance(name, str) or not STEP_NAME_RE.match(name):
        return None
    # Le fichier de template se déduit du nom d'étape : un nom libre laisserait deux
    # étapes pointer le même fichier, ou une étape hors de son répertoire.
    if template != f"{name}{TEMPLATE_SUFFIX}":
        return None
    if target is not None and not isinstance(target, str):
        return None
    return StepDoc(name, target or None)


def slugs_in(paths: list[str]) -> list[str]:
    return sorted({m["slug"] for m in map(_FILE_RE.match, paths) if m is not None})


def files_of(paths: list[str], slug: str) -> list[str]:
    return sorted(
        m["file"] for m in map(_FILE_RE.match, paths) if m is not None and m["slug"] == slug
    )


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
