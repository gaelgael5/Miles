from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
# Annuaire de l'administrateur d'amorçage, qui n'est pas un compte OIDC : son
# identité d'auteur est (« local », nom d'utilisateur).
LOCAL_DIRECTORY = "local"

FunctionalAtSource = Literal["caller", "write_time"]


class EventError(ValueError):
    """Event refusé avant écriture ; le message dit pourquoi."""


@dataclass(frozen=True, order=True)
class ObjectRef:
    kind: str
    id: str

    def __post_init__(self) -> None:
        if not NAME_RE.match(self.kind):
            raise EventError(f"type d'objet invalide : {self.kind!r}")
        if not self.id or len(self.id) > 200:
            raise EventError("identifiant d'objet vide ou trop long")


@dataclass(frozen=True)
class EventAuthor:
    """L'identité utilisée, (annuaire, sub) — jamais la personne."""

    directory: str
    subject: str

    def __post_init__(self) -> None:
        # Un event sans auteur ouvrirait la porte aux events anonymes : refus.
        if not self.directory or not self.subject:
            raise EventError("auteur absent : un event a toujours un auteur")


@dataclass(frozen=True)
class DelegatedAuthor(EventAuthor):
    """Un auteur qui agit par une clé d'API (surface MCP, story 3429986c).

    L'identité reste (annuaire, sub) : la personne signée par le portail (OBO), ou la
    clé elle-même. S'y ajoutent la clé par laquelle l'appel est passé, que l'event et
    le commit doivent dire (« les deux », Gael 22/10/2026), et l'identité git à signer.
    """

    via_key_id: str
    via_key_label: str
    # « Nom <e-mail> » à inscrire comme auteur du commit.
    commit_identity: str
    # « api_key » ou « oauth » : par où l'appel est passé, que l'event et le commit nomment.
    via_kind: str = "api_key"


@dataclass(frozen=True)
class NewEvent:
    type: str
    objects: tuple[ObjectRef, ...]
    author: EventAuthor
    properties: Mapping[str, Any] = field(default_factory=dict)
    functional_at: datetime | None = None
    # Les trois champs que la racine commune apporte (`root.py`, décision du 12/11/2026) :
    # l'identifiant de l'event chez son producteur, sa clé d'anti-doublon, et la date à
    # laquelle il a été créé là-bas. Ils vivent en colonnes, pas dans le bloc de
    # propriétés, et restent facultatifs : un geste humain dans l'atelier n'en a aucun.
    external_id: str | None = None
    dedup_key: str | None = None
    creation_date: datetime | None = None

    def __post_init__(self) -> None:
        if not NAME_RE.match(self.type):
            raise EventError(f"type d'event invalide : {self.type!r}")
        if not self.objects:
            raise EventError("un event concerne au moins un objet")
        if len(set(self.objects)) != len(self.objects):
            raise EventError("objet cité deux fois dans le même event")
        if self.functional_at is not None and self.functional_at.tzinfo is None:
            raise EventError("date fonctionnelle sans fuseau : ambiguë")
        # Même refus que pour la date fonctionnelle : une date sans fuseau se relirait dans
        # celui du serveur, et deux producteurs n'ont pas le même.
        if self.creation_date is not None and self.creation_date.tzinfo is None:
            raise EventError("date de création sans fuseau : ambiguë")
        _checked(self.external_id, "identifiant externe")
        _checked(self.dedup_key, "clé d'anti-doublon")


def _checked(value: str | None, name: str) -> None:
    """Un champ de racine facultatif : absent, ou une vraie valeur — jamais entre les deux.

    La chaîne vide est refusée et non convertie en `None` : reçue d'un producteur, elle dit
    qu'il croyait poser une valeur. La borne de longueur est celle des identifiants
    d'objet : la colonne est libre, et une clé d'anti-doublon de dix kilo-octets passerait.
    """
    if value is None:
        return
    if not value:
        raise EventError(f"{name} vide : l'omettre plutôt que l'envoyer vide")
    if len(value) > 200:
        raise EventError(f"{name} trop long : {len(value)} caractères pour 200 au plus")


@dataclass(frozen=True)
class WrittenEvent:
    id: UUID
    type: str
    functional_at: datetime
    functional_at_source: FunctionalAtSource
    written_at: datetime
    author: EventAuthor
    properties: Mapping[str, Any]
    sequences: Mapping[ObjectRef, int]
    # Sans défaut, et placée avant les champs facultatifs pour cela : la catégorie est
    # toujours connue — elle vient du catalogue, qui l'exige de chaque type déclaré — et
    # un défaut en ferait un repli silencieux le jour où un appelant l'oublierait.
    category: int
    external_id: str | None = None
    dedup_key: str | None = None
    creation_date: datetime | None = None

    @property
    def functional_at_in_future(self) -> bool:
        # Accepté, mais signalé : une date métier postérieure à l'écriture est suspecte.
        return self.functional_at > self.written_at
