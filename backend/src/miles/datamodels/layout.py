from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from miles.datamodels.grammar import NAME_RE
from miles.workspaces.model import WorkspaceInputError

SHARED = "shared"
# Emplacements retenus au cadrage : un modèle transverse sous shared/, un modèle de
# domaine sous domains/<domaine>/. Aucun dossier d'environnement : l'environnement est
# une branche. On ne promeut au transverse qu'au second usage réel.
# Le nom suit la règle d'un nom de modèle : un fichier de métadonnées (`.meta.yaml`) n'est
# jamais pris pour un modèle.
_PATH_RE = re.compile(
    r"^(?:shared/messages/(?P<shared>[a-z0-9][a-z0-9_-]*)"
    r"|domains/(?P<domain>[^/]+)/messages/(?P<name>[a-z0-9][a-z0-9_-]*))\.yaml$"
)


@dataclass(frozen=True)
class ModelEntry:
    scope: str  # « shared », ou le nom du domaine
    name: str
    path: str
    # Hors de l'égalité : un modèle reste le même quel que soit son label.
    label: str | None = field(default=None, compare=False)


def model_path(scope: str, name: str) -> str:
    if scope == SHARED:
        return f"shared/messages/{name}.yaml"
    return f"domains/{scope}/messages/{name}.yaml"


def entry_of(path: str) -> ModelEntry | None:
    match = _PATH_RE.match(path)
    if match is None:
        return None
    if match["shared"] is not None:
        return ModelEntry(SHARED, match["shared"], path)
    return ModelEntry(match["domain"], match["name"], path)


def visible_from(entries: Sequence[ModelEntry], scope: str) -> dict[str, ModelEntry]:
    """Modèles qu'un document de `scope` peut désigner, par nom.

    Un modèle de domaine voit ceux de son domaine puis les transverses, le sien masquant
    un transverse de même nom ; un transverse ne voit que les transverses — il ne peut
    pas dépendre d'un domaine sans cesser d'être transverse.
    """
    visible = {e.name: e for e in entries if e.scope == SHARED}
    if scope != SHARED:
        visible |= {e.name: e for e in entries if e.scope == scope}
    return visible


def checked_scope(scope: str) -> str:
    if scope != SHARED and not NAME_RE.match(scope):
        raise WorkspaceInputError("scope")
    return scope


def checked_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise WorkspaceInputError("name")
    return name
