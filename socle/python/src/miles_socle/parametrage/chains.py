"""Déclaration d'une chaîne de transformations, telle qu'elle est écrite dans le paramétrage.

Une chaîne (story 66ae5c10, Gael 22/10/2026) : des étapes ordonnées par l'utilisateur,
appliquées au même message aux quatre points de passage — source de données, MQTT vers
l'appareil, MQTT depuis l'appareil, webservices externes. Un répertoire par chaîne, un
fichier JSON pour l'enchaînement, un fichier par template.

**Extrait au socle le 03/11/2026** (enabler `b2a215ee`), deuxième usage : le module
d'environnement lit ces mêmes fichiers dans la version qu'il héberge, pour appliquer la
chaîne qu'une entrée de source nomme (story `d680e811`). Seule la LECTURE est ici, comme
pour les sources et les storages le 02/11/2026 : l'écriture (`chain_text`) et le
diagnostic de saisie restent au module de paramétrage, qui seul tient la branche et sait
rendre une erreur à un écran.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from miles_socle.parametrage.layout import target_of

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
    # Modèles que l'étape lit et produit, en URI de modèle (« miles:/shared/colis »).
    # Ajout du 24/10/2026 : l'écran s'en sert pour proposer le gabarit du résultat et
    # pour dire ce que l'étape transforme. Absents sur les chaînes écrites avant, d'où
    # les valeurs nulles — et d'où leur omission à l'écriture, qui laisse ces chaînes
    # inchangées à l'octet près tant qu'on ne les renseigne pas.
    source_model: str | None = None
    destination_model: str | None = None

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
    source = _model_ref(raw.get("source_model"))
    destination = _model_ref(raw.get("destination_model"))
    if source is _INVALID or destination is _INVALID:
        return None
    return StepDoc(name, target or None, source, destination)


# Distingue « absent » d'« illisible » : un None rendu par _model_ref dirait seulement
# qu'il n'y en a pas, et une référence mal formée passerait pour une absence.
_INVALID = "  invalide  "


def _model_ref(raw: object) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or target_of(raw) is None:
        return _INVALID
    return raw


def slugs_in(paths: list[str]) -> list[str]:
    return sorted({m["slug"] for m in map(_FILE_RE.match, paths) if m is not None})


def files_of(paths: list[str], slug: str) -> list[str]:
    return sorted(
        m["file"] for m in map(_FILE_RE.match, paths) if m is not None and m["slug"] == slug
    )
