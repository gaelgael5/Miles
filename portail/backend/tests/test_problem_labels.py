"""Tout code de problème que le backend peut émettre a son libellé, dans les DEUX langues.

Cette garde naît d'une copie d'écran du 01/11/2026 : l'écran affichait
`dataModels.problems.propriete_inconnue` — la clef brute — au lieu d'une phrase. Le
relevé a montré que ce n'était pas un oubli isolé : **45 codes sur 65 n'avaient aucun
libellé**, et chacun d'eux se serait affiché tel quel le jour où il serait émis.

Pourquoi ce test est ICI et pas au front : les codes sont écrits en Python, et seul
l'arbre syntaxique les voit sans se tromper. Un motif textuel côté front confondrait une
chaîne quelconque avec un code, et manquerait les constructions indirectes — qui sont
justement celles qui avaient échappé au premier relevé.

Un code sans libellé n'est pas un détail d'affichage : c'est un refus que personne ne
peut lire, sur l'écran où l'on décide quoi corriger.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SRC = BACKEND / "src"
LOCALES = BACKEND.parents[0] / "frontend" / "src" / "i18n" / "locales"
LANGUES = ("fr-FR", "en-US")

# Les types de problème dont le DEUXIÈME champ est un code. `ContractProblem` en est
# exclu à dessein : son second champ est un `message`, déjà écrit en langue naturelle par
# le validateur OpenAPI, et il ne passe par aucun libellé.
PORTEURS_DE_CODE = ("Problem", "StorageProblem", "SourceProblem", "ReferenceProblem", "StepProblem")

# Codes qu'aucune analyse syntaxique ne peut voir : ils naissent d'une table ou d'une
# interpolation. Écrits à la main — code -> (origine, fragment qui prouve qu'il est
# toujours produit). Le fragment, et non le code lui-même : deux de ces codes sont
# ASSEMBLÉS (`f"manifeste_{état}"`), et leur littéral n'existe nulle part dans les
# sources. Chercher le code aurait rendu ce test rouge en permanence — mesuré en
# l'écrivant ainsi le 01/11/2026.
_CONTENEURS = "table _CONTAINERS (accounts/checks.py, storages/checks.py)"
_MANIFESTE = "f-string « manifeste_<état> » (workshop/validation.py)"
CODES_INDIRECTS = {
    "tableau_interdit": (_CONTENEURS, '"tableau_interdit"'),
    "valeur_attendue": (_CONTENEURS, '"valeur_attendue"'),
    "manifeste_absent": (_MANIFESTE, "manifeste_"),
    "manifeste_invalide": (_MANIFESTE, "manifeste_"),
}


def _codes_litteraux() -> dict[str, str]:
    """Code -> fichier qui l'émet, lus de l'arbre syntaxique de chaque module."""
    trouves: dict[str, str] = {}
    for f in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in PORTEURS_DE_CODE
            ):
                continue
            arg = node.args[1] if len(node.args) >= 2 else None
            for kw in node.keywords:
                if kw.arg == "code":
                    arg = kw.value
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                trouves.setdefault(arg.value, str(f.relative_to(SRC)))
    return trouves


def _libelles(langue: str) -> dict[str, str]:
    data = json.loads((LOCALES / f"{langue}.json").read_text(encoding="utf-8"))
    problemes: dict[str, str] = data["dataModels"]["problems"]
    return problemes


def test_chaque_code_emis_a_son_libelle_dans_les_deux_langues() -> None:
    codes = _codes_litteraux()
    emis = set(codes) | set(CODES_INDIRECTS)
    for langue in LANGUES:
        manquants = sorted(emis - set(_libelles(langue)))
        assert not manquants, (
            f"{len(manquants)} codes sans libellé en {langue}, qui s'afficheraient en clef"
            " brute sur l'écran de validation :\n"
            + "\n".join(f"  {c} — {codes.get(c) or CODES_INDIRECTS[c][0]}" for c in manquants)
        )


def test_les_deux_langues_portent_les_memes_clefs() -> None:
    # Sans ce contrôle, un libellé ajouté dans une seule langue laisserait l'autre
    # afficher la clef — et le test précédent, qui lit les deux, le dirait déjà ; celui-ci
    # le dit en NOMMANT l'écart, y compris pour les libellés qu'aucun code n'émet encore.
    fr, en = set(_libelles("fr-FR")), set(_libelles("en-US"))
    assert fr == en, f"clefs d'un seul côté : {sorted(fr ^ en)}"


def test_les_codes_indirects_declares_existent_toujours_dans_les_sources() -> None:
    """Une liste écrite à la main vieillit : celle-ci est vérifiée contre les sources.

    Sans ce test, un code renommé laisserait sa vieille entrée couvrir un libellé devenu
    inutile, et la garde resterait verte en ne protégeant plus rien — la même panne que
    `test_les_noms_gardes_existent_toujours_au_contrat` évite côté credentials.
    """
    sources = "\n".join(f.read_text(encoding="utf-8") for f in SRC.rglob("*.py"))
    absents = [code for code, (_, fragment) in CODES_INDIRECTS.items() if fragment not in sources]
    assert not absents, f"codes indirects déclarés mais introuvables dans les sources : {absents}"


def test_le_releve_trouve_bien_des_codes() -> None:
    # Un chemin devenu faux ferait passer les tests ci-dessus sur un ensemble VIDE —
    # le vert le plus trompeur qui soit.
    codes = _codes_litteraux()
    assert len(codes) > 40, f"relevé suspect : {len(codes)} codes seulement"
    assert "propriete_inconnue" in codes, "le code de la copie d'écran du 01/11/2026 a disparu"
