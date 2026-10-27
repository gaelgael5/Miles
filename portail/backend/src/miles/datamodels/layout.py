from __future__ import annotations

import re
from dataclasses import dataclass, field

from miles.datamodels.grammar import NAME_RE
from miles.workspaces.model import WorkspaceInputError

SHARED = "shared"
# « portée/nom » : la façon dont une déclaration (storage, source) désigne un modèle.
# Les deux parties suivent EXACTEMENT la règle d'un nom (NAME_RE), dont ce motif est
# dérivé : une copie à la main refusait les tirets et les chiffres en tête, donc des
# modèles que l'écran des modèles accepte de créer — « pudo/import-crm » en est un.
_NAME = NAME_RE.pattern.strip("^$")
MODEL_RE = re.compile(rf"^(?P<scope>{_NAME})/(?P<name>{_NAME})$")
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
    # Hors de l'égalité : un modèle reste le même quel que soit son label ou sa version.
    label: str | None = field(default=None, compare=False)
    # Tenue par le système (métadonnées) ; None si le modèle n'en a pas encore.
    version: int | None = field(default=None, compare=False)


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


def checked_scope(scope: str) -> str:
    if scope != SHARED and not NAME_RE.match(scope):
        raise WorkspaceInputError("scope")
    return scope


def checked_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise WorkspaceInputError("name")
    return name


def visible(entry: ModelEntry, target: tuple[str, str]) -> bool:
    """Un modèle de domaine voit son domaine et les transverses ; un transverse, les seuls
    transverses : il ne peut pas dépendre d'un domaine sans cesser d'être transverse."""
    scope, _ = target
    return scope == "shared" or (entry.scope != "shared" and scope == entry.scope)
