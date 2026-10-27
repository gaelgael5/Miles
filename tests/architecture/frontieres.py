"""Qui a le droit d'importer quoi, entre le socle et les trois produits.

Le cadrage `terminal-pr`, article *Découpage en trois produits*, pose la règle et dit
pourquoi elle doit être mécanique : « Trois produits dans un même dépôt avec des imports
libres redeviennent un seul produit en quelques semaines. Un test d'architecture sur les
imports entre les trois racines suffit. »

On lit les fichiers avec `ast` au lieu d'importer les paquets : la vérification doit
tourner sans qu'aucun environnement de produit soit installé, et un import réel
exécuterait le code qu'on cherche justement à contrôler.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

SOCLE = "socle/python/src"
PRODUITS = ("portail", "enrolement", "environnement")


@dataclass(frozen=True)
class Racine:
    """Une racine de code : son nom parlant, son répertoire, ses paquets de premier niveau."""

    nom: str
    repertoire: Path
    paquets: frozenset[str]


@dataclass(frozen=True)
class Violation:
    fichier: Path
    ligne: int
    importe: str
    racine: str

    def __str__(self) -> str:
        return f"{self.fichier}:{self.ligne} — « {self.racine} » importe « {self.importe} »"


def file_paquets_de(repertoire: Path) -> frozenset[str]:
    """Les paquets et modules de premier niveau exposés par un répertoire `src/`."""
    if not repertoire.is_dir():
        return frozenset()
    paquets = {e.name for e in repertoire.iterdir() if (e / "__init__.py").is_file()}
    modules = {e.stem for e in repertoire.glob("*.py") if e.stem != "__init__"}
    return frozenset(paquets | modules)


def file_racines(depot: Path) -> tuple[Racine, ...]:
    """Les racines présentes : le socle, puis les produits qui existent déjà.

    Les produits absents sont ignorés plutôt que déclarés en erreur : `enrolement/` et
    `environnement/` n'existent pas encore, et ce test doit passer avant comme après.
    """
    racines = [Racine("socle", depot / SOCLE, file_paquets_de(depot / SOCLE))]
    for produit in PRODUITS:
        src = depot / produit / "backend" / "src"
        if src.is_dir():
            racines.append(Racine(produit, src, file_paquets_de(src)))
    return tuple(racines)


def file_imports(fichier: Path) -> tuple[tuple[str, int], ...]:
    """Les modules de premier niveau importés par un fichier, avec leur ligne."""
    arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
    trouves: list[tuple[str, int]] = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            trouves.extend((alias.name.split(".")[0], noeud.lineno) for alias in noeud.names)
        # Un `from . import x` a `module is None` : il est interne par construction,
        # et ne peut donc pas franchir une frontière.
        elif isinstance(noeud, ast.ImportFrom) and noeud.level == 0 and noeud.module:
            trouves.append((noeud.module.split(".")[0], noeud.lineno))
    return tuple(trouves)


def resolve_violations(depot: Path) -> tuple[Violation, ...]:
    """Les franchissements de frontière, pour toutes les racines présentes.

    Deux règles, et elles n'ont pas la même raison :
    - le socle n'importe aucun produit, sinon il ne peut plus être consommé par un autre ;
    - un produit n'importe aucun autre produit, sinon les trois stacks redeviennent une.
    """
    racines = file_racines(depot)
    violations: list[Violation] = []
    for racine in racines:
        interdits = {
            paquet: autre.nom
            for autre in racines
            if autre.nom != racine.nom
            for paquet in autre.paquets
        }
        if racine.nom != "socle":
            # Le socle est fait pour être importé : on le retire des interdits du produit.
            interdits = {p: n for p, n in interdits.items() if n != "socle"}
        for fichier in sorted(racine.repertoire.rglob("*.py")):
            for module, ligne in file_imports(fichier):
                if module in interdits:
                    violations.append(
                        Violation(fichier.relative_to(depot), ligne, module, racine.nom)
                    )
    return tuple(violations)
