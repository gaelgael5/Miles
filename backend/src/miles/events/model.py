from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

_NAME_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
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
        if not _NAME_RE.match(self.kind):
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


@dataclass(frozen=True)
class NewEvent:
    type: str
    objects: tuple[ObjectRef, ...]
    author: EventAuthor
    properties: Mapping[str, Any] = field(default_factory=dict)
    functional_at: datetime | None = None

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.type):
            raise EventError(f"type d'event invalide : {self.type!r}")
        if not self.objects:
            raise EventError("un event concerne au moins un objet")
        if len(set(self.objects)) != len(self.objects):
            raise EventError("objet cité deux fois dans le même event")
        if self.functional_at is not None and self.functional_at.tzinfo is None:
            raise EventError("date fonctionnelle sans fuseau : ambiguë")


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

    @property
    def functional_at_in_future(self) -> bool:
        # Accepté, mais signalé : une date métier postérieure à l'écriture est suspecte.
        return self.functional_at > self.written_at


class EventTypeCatalog:
    """Types d'event admis. Un type inconnu est rejeté (fail closed).

    Le catalogue réel, déclaré dans git, arrive avec son propre ticket ; d'ici là
    le catalogue est vide et aucun event ne passe, ce qui est voulu.
    """

    def __init__(self, known_types: frozenset[str] = frozenset()) -> None:
        self._known = known_types

    def check(self, event_type: str) -> None:
        if event_type not in self._known:
            raise EventError(f"type d'event inconnu du catalogue : {event_type!r}")
