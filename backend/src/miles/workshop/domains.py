from __future__ import annotations

import re
from dataclasses import dataclass, field

# Rubriques d'un domaine, retenues au cadrage (« Back-office — capacités attendues ») ;
# les mappings se rangent par sens. Même découpage que le squelette d'un dépôt.
SECTIONS = (
    "messages",
    "mappings/inbound",
    "mappings/outbound",
    "referentials",
    "components",
    "screens",
    "scenarios",
)
SHARED_MESSAGES = "shared/messages/"
DOMAINS = "domains/"
# Fichiers de place que git exige pour un répertoire vide : jamais un élément.
_PLACEHOLDERS = {".gitkeep"}
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Borne d'une réponse : au-delà, la suite se demande par `after` (critère 11). Assez pour
# un domaine ordinaire, assez peu pour ne pas saturer le contexte d'un agent.
MAX_CONTENT_BYTES = 256 * 1024


class DomainNotFoundError(Exception):
    """Le domaine n'existe pas sur la branche : on nomme ceux qui existent."""

    def __init__(self, name: str, existing: list[str]) -> None:
        super().__init__(name)
        self.name, self.existing = name, existing


@dataclass(frozen=True)
class Element:
    path: str
    # None : au-delà de la borne de la réponse, à redemander par `after`.
    content: str | None


@dataclass
class DomainContent:
    name: str
    sections: dict[str, list[Element]] = field(default_factory=lambda: {s: [] for s in SECTIONS})
    # Fichiers du domaine hors des rubriques attendues : rendus, jamais ignorés (critère 10).
    misplaced: list[Element] = field(default_factory=list)
    # Vrai quand la borne a été atteinte : `next_after` dit d'où reprendre.
    truncated: bool = False
    next_after: str | None = None


def domains_in(paths: list[str]) -> list[str]:
    """Les domaines d'une branche : les répertoires de `domains/`, vides compris."""
    found = {p.split("/")[1] for p in paths if p.startswith(DOMAINS) and p.count("/") >= 2}
    return sorted(found)


def checked_domain(name: str) -> str:
    if not _DOMAIN_RE.match(name):
        # Le nom devient un préfixe de chemin : refusé avant tout usage.
        raise ValueError("nom de domaine invalide")
    return name


def section_of(relative: str) -> str | None:
    """La rubrique d'un fichier, d'après son chemin dans le domaine ; None : hors rubrique."""
    for section in SECTIONS:
        if relative.startswith(section + "/") and "/" not in relative[len(section) + 1 :]:
            return section
    return None


def domain_files(paths: list[str], name: str) -> list[str]:
    prefix = f"{DOMAINS}{name}/"
    return sorted(
        p for p in paths if p.startswith(prefix) and p.rsplit("/", 1)[-1] not in _PLACEHOLDERS
    )


def shared_messages(paths: list[str]) -> list[str]:
    return sorted(
        p
        for p in paths
        if p.startswith(SHARED_MESSAGES)
        and "/" not in p[len(SHARED_MESSAGES) :]
        and p.rsplit("/", 1)[-1] not in _PLACEHOLDERS
    )
