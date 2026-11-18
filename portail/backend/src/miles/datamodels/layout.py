from __future__ import annotations

import re
from dataclasses import dataclass, field

from miles_socle.parametrage.layout import DEVICE_SCOPES as DEVICE_SCOPES
from miles_socle.parametrage.layout import DEVICES as DEVICES
from miles_socle.parametrage.layout import INBOUND as INBOUND
from miles_socle.parametrage.layout import MODEL_RE as MODEL_RE
from miles_socle.parametrage.layout import OUTBOUND as OUTBOUND
from miles_socle.parametrage.layout import SHARED as SHARED
from miles_socle.parametrage.layout import model_path as model_path

from miles.datamodels.grammar import NAME_RE
from miles.workspaces.model import WorkspaceInputError

# Le nom suit la règle d'un nom de modèle : un fichier de métadonnées (`.meta.yaml`)
# n'est jamais pris pour un modèle.
_SENSES = "|".join(DEVICE_SCOPES.values())
_PATH_RE = re.compile(
    r"^(?:shared/models/(?P<shared>[a-z0-9][a-z0-9_-]*)"
    rf"|{DEVICES}/(?P<sens>{_SENSES})/(?P<device>[a-z0-9][a-z0-9_-]*)"
    r"|domains/(?P<domain>[^/]+)/models/(?P<name>[a-z0-9][a-z0-9_-]*))\.yaml$"
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


def entry_of(path: str) -> ModelEntry | None:
    match = _PATH_RE.match(path)
    if match is None:
        return None
    if match["shared"] is not None:
        return ModelEntry(SHARED, match["shared"], path)
    if match["sens"] is not None:
        return ModelEntry(f"{DEVICES}-{match['sens']}", match["device"], path)
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
    transverses : il ne peut pas dépendre d'un domaine sans cesser d'être transverse.

    **Les modèles devices (story 31025fe6) tombent sous la MÊME règle sans qu'elle change**,
    et c'est pourquoi aucune ligne n'est ajoutée ici : la portée d'un sens n'est ni
    `shared` ni celle d'un autre sens, donc un modèle device voit les transverses et les
    devices de SON sens, jamais un domaine ni l'autre sens — et aucun transverse ni modèle
    de domaine ne le voit. C'est mot pour mot le « chacun chez soi » demandé. Qui
    particulariserait les devices ici écrirait deux fois la même règle.
    """
    scope, _ = target
    return scope == "shared" or (entry.scope != "shared" and scope == entry.scope)
