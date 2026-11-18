from __future__ import annotations

import re
from dataclasses import dataclass, field

from miles_socle.parametrage.layout import DEVICE_SCOPES, SHARED

# Nom de la rubrique du seul artefact de déclaration du domaine, et suffixe de son
# fichier : voir `miles.workflowevents.dsl`, dont `fragment_path` est seul à composer le
# chemin. Recopié ici pour la même raison que dans la couche git — ce module ne connaît
# pas les types d'event —, et `test_tree_layout.py` refuse que les deux divergent.
EVENT_TYPES = "event-types"
FRAGMENT_SUFFIX = ".wf"

# Rubriques d'un domaine, retenues au cadrage (« Back-office — capacités attendues ») ;
# les mappings se rangent par sens. Même découpage que le squelette d'un dépôt.
SECTIONS = (
    "models",
    # Les types d'event du domaine. UNE rubrique à un seul fichier, et non un dossier :
    # depuis le 14/11/2026, un type d'event n'est plus un fichier mais une déclaration de
    # l'artefact du périmètre (`domains/<d>/<d>.wf`). Rendu sous un nom qui dit ce qu'il
    # est, plutôt que rangé dans `misplaced` — ce que `section_of` en ferait sinon, et un
    # agent conclurait que le dépôt porte un fichier égaré.
    EVENT_TYPES,
    "mappings/inbound",
    "mappings/outbound",
    "referentials",
    "components",
    "screens",
    "scenarios",
)
SHARED_MODELS = "shared/models/"
DOMAINS = "domains/"
# Fichiers de place que git exige pour un répertoire vide : jamais un élément. Les
# métadonnées d'un modèle (`<nom>.meta.yaml`, sa version) sont au système, pas au domaine.
_PLACEHOLDERS = {".gitkeep"}
_META_SUFFIX = ".meta.yaml"
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Portées qui ne sont pas des domaines : le transverse et les deux sens du tuyau terminal.
# Importées du socle, qui les POSE : ici un nom recopié finirait par ne plus réserver la
# bonne chose, et la collision ne se verrait qu'à l'usage.
_RESERVED_SCOPES = frozenset({SHARED, *DEVICE_SCOPES})
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


def reserved_scope(name: str) -> bool:
    """Ce nom est-il celui d'une portée que le dépôt range AILLEURS que sous `domains/` ?

    Vrai pour `shared` et pour les deux portées de sens (story 31025fe6). Un domaine qui
    porterait l'un de ces noms rendrait deux fichiers pour une seule identité :
    `domains/devices-inbound/models/x.yaml` et `devices/inbound/x.yaml` donnent la même
    portée et le même nom, et savoir lequel est écrit puis relu deviendrait un hasard de
    l'ordre de parcours. `shared` est de la même famille, et était déjà exposé.

    **Interrogé par le geste de CRÉATION seulement, jamais par la lecture** : un dépôt
    ouvert avant cette story peut porter un tel domaine, et il doit rester lisible — c'est
    la seule façon de voir ce qu'il contient pour le vider.
    """
    return name in _RESERVED_SCOPES


def section_of(relative: str, domain: str) -> str | None:
    """La rubrique d'un fichier, d'après son chemin dans le domaine ; None : hors rubrique.

    Le domaine est demandé parce que son artefact de déclaration porte SON nom : c'est la
    seule rubrique dont le nom de fichier dépend du domaine.
    """
    if relative == f"{domain}{FRAGMENT_SUFFIX}":
        return EVENT_TYPES
    for section in SECTIONS:
        if relative.startswith(section + "/") and "/" not in relative[len(section) + 1 :]:
            return section
    return None


def domain_files(paths: list[str], name: str) -> list[str]:
    prefix = f"{DOMAINS}{name}/"
    return sorted(
        p
        for p in paths
        if p.startswith(prefix)
        and p.rsplit("/", 1)[-1] not in _PLACEHOLDERS
        and not p.endswith(_META_SUFFIX)
    )


def shared_models(paths: list[str]) -> list[str]:
    return sorted(
        p
        for p in paths
        if p.startswith(SHARED_MODELS)
        and "/" not in p[len(SHARED_MODELS) :]
        and p.rsplit("/", 1)[-1] not in _PLACEHOLDERS
        and not p.endswith(_META_SUFFIX)
    )
