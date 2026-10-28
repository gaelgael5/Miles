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
import re
from dataclasses import dataclass
from pathlib import Path

SOCLE = "socle/python/src"
SOCLE_WEB = "socle/web/src"
PRODUITS = ("portail", "enrolement", "environnement")

# Seule référence admise d'un produit vers le socle web : le nom du paquet. Tout chemin
# relatif qui sort de la racine est un franchissement, y compris vers le socle — sinon
# un produit pourrait atteindre le front d'un autre par « ../../autre/frontend/src ».
PAQUET_SOCLE_WEB = "@miles/socle-web"


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


# --- Frontière côté TypeScript ---------------------------------------------------------
# Les fronts n'ont pas de paquets de premier niveau comme Python : la règle s'exprime
# donc sur les chemins. Un import RELATIF qui sort de sa racine est un franchissement,
# et c'est tout ce qu'il y a à vérifier — le socle web n'est atteignable que par le nom
# de son paquet, et aucun produit n'est un paquet.
_SPECIFICATEUR = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*)["']([^"']+)["']""")


def file_racines_web(depot: Path) -> tuple[Racine, ...]:
    """Les racines de code front présentes : le socle web, puis les produits qui existent.

    Même règle que pour Python : un produit absent du disque est ignoré, pour que ce test
    passe avant comme après la création de `enrolement/` et `environnement/`.
    """
    racines: list[Racine] = []
    socle = depot / SOCLE_WEB
    if socle.is_dir():
        racines.append(Racine("socle-web", socle, frozenset()))
    for produit in PRODUITS:
        src = depot / produit / "frontend" / "src"
        if src.is_dir():
            racines.append(Racine(produit, src, frozenset()))
    return tuple(racines)


def file_imports_web(fichier: Path) -> tuple[tuple[str, int], ...]:
    """Les spécificateurs de module importés par un fichier TypeScript, avec leur ligne.

    Lu par expression régulière et non par un analyseur TypeScript : la vérification doit
    tourner sans node ni dépendances installées, comme son équivalent Python tourne sans
    l'environnement des produits.
    """
    texte = fichier.read_text(encoding="utf-8")
    trouves: list[tuple[str, int]] = []
    for correspondance in _SPECIFICATEUR.finditer(texte):
        ligne = texte.count("\n", 0, correspondance.start()) + 1
        trouves.append((correspondance.group(1), ligne))
    return tuple(trouves)


def resolve_violations_web(depot: Path) -> tuple[Violation, ...]:
    """Les franchissements de frontière entre les fronts du socle et des produits."""
    violations: list[Violation] = []
    for racine in file_racines_web(depot):
        for fichier in sorted(racine.repertoire.rglob("*.ts")) + sorted(
            racine.repertoire.rglob("*.tsx")
        ):
            for specificateur, ligne in file_imports_web(fichier):
                if not specificateur.startswith("."):
                    continue
                vise = (fichier.parent / specificateur).resolve()
                if vise.is_relative_to(racine.repertoire.resolve()):
                    continue
                violations.append(
                    Violation(fichier.relative_to(depot), ligne, specificateur, racine.nom)
                )
    return tuple(violations)


# --- Frontière côté shell ---------------------------------------------------------------
# Les scripts de déploiement sourcent depuis le 28/10/2026 les gardes du socle
# (`socle/deploy/gardes.sh`). C'est une référence inter-racines de plus, et elle
# n'apparaît ni dans les imports Python ni dans ceux de TypeScript : sans la règle
# ci-dessous, un produit pourrait sourcer le script d'un autre sans que rien ne le voie.
#
# Règle : un script shell d'un produit ne référence par chemin aucun AUTRE produit. Le
# socle, lui, est la raison d'être du partage. Et le socle ne référence aucun produit.
SOCLE_DEPLOY = "socle/deploy"
_SOURCE_SHELL = re.compile(r"^[ \t]*(?:source|\.)[ \t]+(\S+)", re.MULTILINE)


def file_sources_shell(fichier: Path) -> tuple[tuple[str, int], ...]:
    """Les cibles de `source` (ou `.`) d'un script, avec leur ligne.

    Lu par motif et non en exécutant le script : il arrête des stacks et déploie. Les
    cibles portent des variables (`$DEPOT_DIR/...`) ; seuls leurs composants littéraux
    sont jugés, ce qui suffit à voir un nom de produit dans un chemin.
    """
    texte = fichier.read_text(encoding="utf-8")
    trouves: list[tuple[str, int]] = []
    for correspondance in _SOURCE_SHELL.finditer(texte):
        ligne = texte.count("\n", 0, correspondance.start()) + 1
        trouves.append((correspondance.group(1), ligne))
    return tuple(trouves)


def resolve_violations_shell(depot: Path) -> tuple[Violation, ...]:
    """Les franchissements de frontière entre scripts shell."""
    violations: list[Violation] = []
    racines: list[tuple[str, Path]] = [("socle", depot / "socle")]
    racines += [(produit, depot / produit) for produit in PRODUITS]
    for nom, repertoire in racines:
        if not repertoire.is_dir():
            continue
        interdits = [autre for autre, _ in racines if autre != nom and autre != "socle"]
        if nom == "socle":
            # Le socle ne référence aucun produit : il serait sinon inconsommable par un autre.
            interdits = [produit for produit in PRODUITS]
        for fichier in sorted(repertoire.rglob("*.sh")):
            for cible, ligne in file_sources_shell(fichier):
                for interdit in interdits:
                    if f"/{interdit}/" in cible or cible.startswith(f"{interdit}/"):
                        violations.append(Violation(fichier.relative_to(depot), ligne, cible, nom))
    return tuple(violations)
