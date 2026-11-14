"""Détecter la disposition du dépôt de paramétrage, et dire comment la convertir.

Deux déplacements, tous deux vers `models/`, et tous deux pour la même raison — ce dossier
ne contient plus seulement des messages :

- `messages/` → `models/` le 13/11/2026. Le nom venait du vocabulaire du « message
  pivot », et un dossier dont le nom ne dit plus ce qu'il contient se fait mal ranger ;
- `events/` → `models/` le 14/11/2026. **Un type d'event n'est plus un fichier** : son
  payload est un modèle ordinaire, et ce qui en fait un type d'event est la déclaration
  `DEFINE EVENT … AS @modele` de l'artefact de son périmètre. La conversion déplace donc
  le schéma ET écrit la déclaration qui lui rend son rôle — sans elle, le dépôt perdrait
  l'information qui distinguait un event d'un modèle.

**Un dépôt ouvert avant ces jours-là ne se lit pas à moitié.** `model_path` pointerait vers
`models/`, n'y trouverait rien, et les modèles auraient l'air supprimés : une panne
silencieuse sur le paramétrage d'un client, découverte au moment où il ouvre son écran.

**Et rien ne se convertit tout seul.** Un dépôt ancien est REFUSÉ, en nommant le geste
qui le convertit ; ce geste écrit un commit. Convertir sur une simple lecture écrirait
dans le dépôt d'un client sans qu'il l'ait demandé, et laisserait un commit que personne
n'attend. Git donne le `revert` d'un commit relu ; il ne donne rien contre une écriture
que personne n'a vue passer.

Module PUR : il ne touche ni git ni disque. C'est ce qui permet de l'éprouver entièrement
sur des listes de chemins, et c'est nécessaire — il décide du refus d'ouverture de TOUTES
les branches de TOUS les workspaces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Les anciens noms de dossier et le nouveau. Nommés plutôt qu'écrits dans le motif : le
# jour où un troisième déplacement arrive, c'est ici qu'on regarde.
MESSAGES = "messages"
EVENTS = "events"
NOUVEAU = "models"
ANCIENS = (MESSAGES, EVENTS)

# Un chemin du dossier des modèles, dans l'une ou l'autre disposition. Le `.meta.yaml`
# d'un modèle et le `.gitkeep` d'un dossier vide sont volontairement DEDANS : ils se
# déplacent avec, sinon la version d'un modèle resterait derrière lui.
_DOSSIER_RE = re.compile(
    rf"^(?P<portee>shared|domains/(?P<domaine>[^/]+))"
    rf"/(?P<dossier>{'|'.join((*ANCIENS, NOUVEAU))})/(?P<reste>.+)$"
)
# Le nom d'un ex-event, pour le déclarer : son fichier de schéma, et lui seul.
_SCHEMA_RE = re.compile(r"^(?P<nom>[a-z0-9][a-z0-9_]*)\.yaml$")

A_JOUR = "a_jour"
ANCIENNE = "ancienne"
MELANGEE = "melangee"

# Le marqueur que git exige pour garder un dossier vide visible. **Il ne compte pas comme
# un contenu**, et c'est décisif ici : le squelette d'une branche crée `shared/models/
# .gitkeep`, donc un dépôt ancien dont le squelette a été rafraîchi porterait les deux
# dossiers. Le compter aurait rendu ce dépôt « mélangé », donc refusé — et refusé SANS
# issue, puisque la conversion elle-même refuse un dépôt mélangé. Mesuré le 13/11/2026
# en montant le test d'intégration : la version précédente de ce module tombait dedans.
# `domains.py` porte la même règle, et pour la même raison : « jamais un élément ».
_MARQUEURS = frozenset({".gitkeep"})


@dataclass(frozen=True)
class Move:
    """Un fichier à déplacer, et ce qu'il était."""

    source: str
    target: str
    # (portée, nom) quand la source est le SCHÉMA d'un ex-event. Porté par le déplacement
    # et non déduit après coup : c'est ce qui dit à la fois de réécrire son `$id` — il
    # portait `miles:/events/…`, qu'aucun storage ne résout — et de le déclarer dans
    # l'artefact de son périmètre.
    event: tuple[str, str] | None = None


@dataclass(frozen=True)
class Layout:
    """Ce que la liste des chemins dit de la disposition du dépôt."""

    kind: str
    # Les déplacements à appliquer, triés. Vide sauf si `ancienne`.
    moves: tuple[Move, ...] = ()
    # Les ex-events dont le nom est DÉJÀ pris par un modèle du même périmètre : la
    # conversion s'arrête dessus plutôt que d'en écraser un. Deux schémas de même nom
    # n'ont pas de bonne réponse automatique.
    conflicts: tuple[str, ...] = field(default=())

    @property
    def refusal(self) -> str | None:
        """Le motif de refus d'ouverture, ou None quand la branche est ouvrable."""
        if self.kind == ANCIENNE:
            return "disposition_ancienne"
        if self.kind == MELANGEE:
            return "disposition_melangee"
        return None

    @property
    def event_types(self) -> tuple[tuple[str, str], ...]:
        """Les ex-events à déclarer, (portée, nom)."""
        return tuple(m.event for m in self.moves if m.event is not None)


def layout_of(paths: list[str]) -> Layout:
    """La disposition d'une branche, d'après ses chemins.

    `melangee` n'est pas un cas théorique : il arrive dès qu'une conversion a été
    interrompue, ou qu'une branche convertie a été fusionnée avec une qui ne l'était pas.
    On refuse alors au lieu de deviner laquelle des deux fait foi — un modèle présent des
    deux côtés avec deux contenus n'a pas de bonne réponse automatique.

    Le mélange ne se juge QUE sur `messages/`, et pas sur `events/` : `events/` et
    `models/` ont légitimement cohabité du 11/11 au 14/11/2026 — c'étaient deux rubriques
    du squelette. Les compter ensemble aurait rendu « mélangé » tout dépôt ouvert dans
    cette fenêtre, donc refusé sans issue.
    """
    anciens = [p for p in paths if _dossier_de(p) in ANCIENS]
    # Les marqueurs sont écartés de la DÉCISION mais gardés dans les déplacements : c'est
    # ce qui fait disparaître l'ancien dossier au lieu d'y laisser un `.gitkeep` orphelin,
    # qui rendrait le dépôt éternellement « ancien ».
    if not _porte_du_contenu(anciens):
        return Layout(A_JOUR)
    renommes = [p for p in paths if _dossier_de(p) == MESSAGES]
    if _porte_du_contenu(renommes) and _porte_du_contenu(
        [p for p in paths if _dossier_de(p) == NOUVEAU]
    ):
        return Layout(MELANGEE)
    moves = tuple(sorted((_move(p) for p in anciens), key=lambda m: m.source))
    arrivees = {p for p in paths if _dossier_de(p) == NOUVEAU}
    conflicts = tuple(sorted(m.target for m in moves if m.target in arrivees))
    return Layout(ANCIENNE, moves, conflicts)


def _porte_du_contenu(chemins: list[str]) -> bool:
    return any(p.rsplit("/", 1)[-1] not in _MARQUEURS for p in chemins)


def _dossier_de(path: str) -> str | None:
    match = _DOSSIER_RE.match(path)
    return None if match is None else match["dossier"]


def _move(path: str) -> Move:
    """Le déplacement d'un chemin. Remplace le SEUL segment de dossier, jamais le reste :
    un modèle nommé `messages.yaml` garde son nom."""
    match = _DOSSIER_RE.match(path)
    if match is None:  # pragma: no cover — appelé seulement sur un chemin déjà reconnu
        raise ValueError(path)
    prefixe = path[: match.start("dossier")]
    target = f"{prefixe}{NOUVEAU}/{match['reste']}"
    schema = _SCHEMA_RE.match(match["reste"]) if match["dossier"] == EVENTS else None
    if schema is None:
        return Move(path, target)
    return Move(path, target, (match["domaine"] or match["portee"], schema["nom"]))
