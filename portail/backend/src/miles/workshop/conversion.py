"""Détecter la disposition du dépôt de paramétrage, et dire comment la convertir.

Le dossier des modèles s'appelait `messages/` jusqu'au 13/11/2026 — du vocabulaire du
« message pivot ». Il porte `models/` depuis, parce qu'il ne contient plus seulement des
messages : les schémas des types d'event y entrent aussi.

**Un dépôt ouvert avant ce jour ne se lit pas à moitié.** `model_path` pointerait vers
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
from dataclasses import dataclass

# L'ancien nom et le nouveau. Nommés plutôt qu'écrits dans le motif : le jour où un
# troisième déplacement arrive, c'est ici qu'on regarde.
ANCIEN = "messages"
NOUVEAU = "models"

# Un chemin du dossier des modèles, dans l'une ou l'autre disposition. Le `.meta.yaml`
# d'un modèle et le `.gitkeep` d'un dossier vide sont volontairement DEDANS : ils se
# déplacent avec, sinon la version d'un modèle resterait derrière lui.
_DOSSIER_RE = re.compile(
    rf"^(?:shared|domains/[^/]+)/(?P<dossier>{ANCIEN}|{NOUVEAU})/(?P<reste>.+)$"
)

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
class Layout:
    """Ce que la liste des chemins dit de la disposition du dépôt."""

    kind: str
    # Les déplacements à appliquer, (ancien, nouveau), triés. Vide sauf si `ancienne`.
    moves: tuple[tuple[str, str], ...] = ()

    @property
    def refusal(self) -> str | None:
        """Le motif de refus d'ouverture, ou None quand la branche est ouvrable."""
        if self.kind == ANCIENNE:
            return "disposition_ancienne"
        if self.kind == MELANGEE:
            return "disposition_melangee"
        return None


def layout_of(paths: list[str]) -> Layout:
    """La disposition d'une branche, d'après ses chemins.

    `melangee` n'est pas un cas théorique : il arrive dès qu'une conversion a été
    interrompue, ou qu'une branche convertie a été fusionnée avec une qui ne l'était pas.
    On refuse alors au lieu de deviner laquelle des deux fait foi — un modèle présent des
    deux côtés avec deux contenus n'a pas de bonne réponse automatique.
    """
    anciens = [p for p in paths if _dossier_de(p) == ANCIEN]
    # Les marqueurs sont écartés de la DÉCISION mais gardés dans les déplacements : c'est
    # ce qui fait disparaître l'ancien dossier au lieu d'y laisser un `.gitkeep` orphelin,
    # qui rendrait le dépôt éternellement « ancien ».
    if not _porte_du_contenu(anciens):
        return Layout(A_JOUR)
    if _porte_du_contenu([p for p in paths if _dossier_de(p) == NOUVEAU]):
        return Layout(MELANGEE)
    return Layout(ANCIENNE, tuple(sorted((p, _deplace(p)) for p in anciens)))


def _porte_du_contenu(chemins: list[str]) -> bool:
    return any(p.rsplit("/", 1)[-1] not in _MARQUEURS for p in chemins)


def _dossier_de(path: str) -> str | None:
    match = _DOSSIER_RE.match(path)
    return None if match is None else match["dossier"]


def _deplace(path: str) -> str:
    """Le chemin d'arrivée. Remplace le SEUL segment de dossier, jamais le reste : un
    modèle nommé `messages.yaml` garde son nom."""
    match = _DOSSIER_RE.match(path)
    if match is None:  # pragma: no cover — appelé seulement sur un chemin déjà reconnu
        raise ValueError(path)
    prefixe = path[: match.start("dossier")]
    return f"{prefixe}{NOUVEAU}/{match['reste']}"
