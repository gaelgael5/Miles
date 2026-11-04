"""Aucun credential git n'atteint un module d'environnement, par aucun chemin.

C'est l'interdit central du ticket edcf78bc, et son critère 10 demande qu'il soit « tenu
par un test d'architecture, parce que c'est la facilité qui se présentera le jour où le
relais sera lent ». La décision de sécurité qu'il protège : le secret s'arrête au module
d'enrôlement, qui le détient pour le compte des environnements. Deux propriétés en
découlent, et elles tombent toutes les deux si un environnement reçoit un jour le
credential — un environnement compromis ne livre pas l'accès au dépôt, et un environnement
révoqué perd son accès à git sans qu'on révoque quoi que ce soit chez la forge.

Ce module lit les SOURCES, sans rien importer : la vérification doit tourner sans qu'aucun
environnement de produit soit installé, et un import réel exécuterait le code contrôlé.

La liste des noms est écrite ici, et un second test vérifie que chacun existe TOUJOURS au
socle : sans lui, renommer un modèle du contrat désarmerait cette garde en silence, et elle
resterait verte pour toujours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

CONTRAT = "socle/python/src/miles_socle/signing/protocol.py"
ENVIRONNEMENT = "environnement"
# Extensions lues : tout ce qui peut porter une référence à un nom du contrat, du backend
# au front en passant par les scripts de déploiement.
SUFFIXES = (".py", ".ts", ".tsx", ".sh", ".sql", ".json")
# Ce que `node_modules` contient ne vient pas de nous, et le lire ferait durer le test des
# minutes pour rien.
IGNORES = ("node_modules", ".venv", "__pycache__", "dist", ".git")

# Nom du contrat → ce qu'on perd si un module d'environnement le nomme. La raison est ici
# parce qu'un test qui échoue doit dire ce qu'on s'apprête à perdre, pas seulement qu'un
# mot a été trouvé.
NOMS_PORTEURS_DE_CREDENTIAL = {
    "GIT_CONNECTIONS_PATH": (
        "la route par laquelle les credentials git voyagent ; un module d'environnement "
        "qui la nomme s'apprête à en demander ou à en servir"
    ),
    "ConfidedGitConnection": (
        "la forme qui PORTE le credential ; aucun module d'environnement n'a de raison "
        "de savoir la lire"
    ),
    "ConfideGitConnectionsIn": ("la charge complète du confiage, credentials compris"),
}


@dataclass(frozen=True)
class Fuite:
    fichier: Path
    ligne: int
    nom: str

    def __str__(self) -> str:
        return (
            f"{self.fichier}:{self.ligne} — le module d'environnement nomme « {self.nom} » : "
            f"{NOMS_PORTEURS_DE_CREDENTIAL[self.nom]}"
        )


def file_sources(racine: Path) -> list[Path]:
    """Les fichiers de code d'une racine, sans ce qui est installé ou engendré."""
    if not racine.is_dir():
        return []
    return sorted(
        chemin
        for chemin in racine.rglob("*")
        if chemin.suffix in SUFFIXES
        and chemin.is_file()
        and not any(part in IGNORES for part in chemin.parts)
    )


def resolve_fuites(depot: Path) -> tuple[Fuite, ...]:
    """Les endroits où le module d'environnement nomme une pièce porteuse de credential."""
    motifs = {nom: re.compile(rf"\b{re.escape(nom)}\b") for nom in NOMS_PORTEURS_DE_CREDENTIAL}
    fuites: list[Fuite] = []
    for chemin in file_sources(depot / ENVIRONNEMENT):
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        for numero, ligne in enumerate(texte.splitlines(), start=1):
            fuites.extend(
                Fuite(chemin.relative_to(depot), numero, nom)
                for nom, motif in motifs.items()
                if motif.search(ligne)
            )
    return tuple(fuites)


def resolve_noms_inconnus_du_contrat(depot: Path) -> tuple[str, ...]:
    """Les noms gardés ici qui n'existent plus au contrat.

    Sans ce contrôle, renommer un modèle du contrat désarmerait la garde sans que rien ne
    rougisse : elle chercherait un mot que plus personne n'écrit.
    """
    texte = (depot / CONTRAT).read_text(encoding="utf-8")
    return tuple(
        nom
        for nom in NOMS_PORTEURS_DE_CREDENTIAL
        if not re.search(rf"^(class {re.escape(nom)}\b|{re.escape(nom)} =)", texte, re.M)
    )
