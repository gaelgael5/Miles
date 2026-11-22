"""Tout code que le backend peut émettre a son libellé, dans les DEUX langues.

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

Deux familles de codes, et la seconde est arrivée par récidive. Le 15/11/2026, une copie
d'écran de Gael montrait `dataModels.errors.conflict.disposition_ancienne` : la garde
écrite le 01/11 ne couvrait que les codes de PROBLÈME, et les codes de REFUS — ceux des
`WorkspaceConflictError` — n'étaient tenus par rien. Relevé du jour : **14 codes sur 31**
sans aucun libellé. Une garde qui ne couvre qu'une famille laisse croire que la famille
voisine est tenue ; les deux sont ici, dans le même fichier, pour qu'on les voie ensemble.
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
_HERITAGE = "constantes RECURSIVE et TOO_DEEP (workflowevents/inheritance.py)"
_PAYLOAD = "constante PAYLOAD (datamodels/payloads.py)"
CODES_INDIRECTS = {
    "tableau_interdit": (_CONTENEURS, '"tableau_interdit"'),
    "valeur_attendue": (_CONTENEURS, '"valeur_attendue"'),
    "manifeste_absent": (_MANIFESTE, "manifeste_"),
    "manifeste_invalide": (_MANIFESTE, "manifeste_"),
    # Deux codes nommés par une constante : le refus est émis depuis deux modules — le
    # module de l'héritage et le service —, et une chaîne recopiée aux deux endroits
    # aurait divergé au premier renommage.
    "heritage_recursif": (_HERITAGE, '"heritage_recursif"'),
    "heritage_trop_profond": (_HERITAGE, '"heritage_trop_profond"'),
    # Même raison : le storage et la source rendent ce refus chacun dans son type de
    # manquement, et c'est la même règle — une chaîne recopiée aux deux endroits aurait
    # divergé au premier renommage.
    "modele_de_payload": (_PAYLOAD, '"modele_de_payload"'),
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


# --- Codes de REFUS (`WorkspaceConflictError`), seconde famille, ajoutée le 15/11/2026 ---

# La racine de la famille : les sous-classes sont trouvées par fermeture transitive sur
# leur nom de base, et non énumérées — une sous-classe ajoutée entre dans la garde toute
# seule, ce qu'une liste écrite à la main n'aurait pas fait.
RACINE_DES_REFUS = "WorkspaceConflictError"

# Codes qu'aucune analyse syntaxique ne voit, pour la même raison que `CODES_INDIRECTS` :
# ils transitent par une variable. Code -> (origine, fragment qui prouve qu'il est
# toujours produit).
_DISPOSITION = "propriété `Layout.refusal` (workshop/conversion.py)"
REFUS_INDIRECTS = {
    "disposition_ancienne": (_DISPOSITION, '"disposition_ancienne"'),
    "disposition_melangee": (_DISPOSITION, '"disposition_melangee"'),
}

# Codes que l'écran ne cherche PAS par leur nom : un composant les reconnaît et choisit
# un libellé nommé autrement, parce que le message porte des valeurs qui lui sont propres.
# Code -> (fichier du front, fragment qui prouve que la correspondance existe toujours).
# Sans cette liste, la garde exigerait un second libellé pour le même refus — deux
# phrases pour une seule chose, qui divergeraient.
REFUS_TRADUITS_AILLEURS = {
    "contexte_pris": ("workspaces/tradsRefusal.tsx", 'detail?.code === "contexte_pris"'),
    "culture_defaut_incomplete": (
        "workspaces/WorkspaceCultures.tsx",
        'detail?.code === "culture_defaut_incomplete"',
    ),
}

# `src/` du front : LOCALES vaut `<front>/src/i18n/locales`.
FRONT_SRC = LOCALES.parents[1]


def _familles_de_refus() -> set[str]:
    """Les classes de refus, racine comprise, par fermeture transitive sur les bases."""
    familles = {RACINE_DES_REFUS}
    arbres = [ast.parse(f.read_text(encoding="utf-8")) for f in sorted(SRC.rglob("*.py"))]
    # Plusieurs passes : une sous-classe peut être déclarée dans un fichier lu avant
    # celui de sa base. Le point fixe est atteint en deux tours sur l'arbre actuel ; la
    # boucle s'arrête d'elle-même, elle ne compte pas les niveaux.
    grandi = True
    while grandi:
        grandi = False
        for arbre in arbres:
            for node in ast.walk(arbre):
                if (
                    isinstance(node, ast.ClassDef)
                    and node.name not in familles
                    and any(isinstance(b, ast.Name) and b.id in familles for b in node.bases)
                ):
                    familles.add(node.name)
                    grandi = True
    return familles


def _codes_de_refus() -> dict[str, str]:
    """Code -> fichier qui l'émet, levé en appelant la classe ou par `super().__init__`."""
    familles = _familles_de_refus()
    trouves: dict[str, str] = {}

    def retiens(arg: ast.expr | None, fichier: Path) -> None:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            trouves.setdefault(arg.value, str(fichier.relative_to(SRC)))

    for f in sorted(SRC.rglob("*.py")):
        arbre = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(arbre):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in familles and node.args:
                    retiens(node.args[0], f)
            # Une sous-classe fige son code : `super().__init__("branche_tenue")`. Sans
            # cette branche, les codes des 13 sous-classes échappaient au relevé.
            if isinstance(node, ast.ClassDef) and node.name in familles:
                for interne in ast.walk(node):
                    if (
                        isinstance(interne, ast.Call)
                        and isinstance(interne.func, ast.Attribute)
                        and interne.func.attr == "__init__"
                        and interne.args
                    ):
                        retiens(interne.args[0], f)
    return trouves


def _clefs_de_libelle(langue: str) -> set[str]:
    """Toute clef de libellé, à n'importe quelle profondeur.

    Volontairement plus large que `dataModels.errors.conflict` : un même code s'affiche
    selon l'écran sous `versions.errors.conflict`, `holds.errors` ou `tradsKeys.errors`,
    et exiger un bloc précis aurait fait écrire des doublons plutôt que des libellés.
    """
    clefs: set[str] = set()

    def descends(noeud: dict[str, object]) -> None:
        for clef, valeur in noeud.items():
            if isinstance(valeur, dict):
                descends(valeur)
            else:
                clefs.add(clef)

    descends(json.loads((LOCALES / f"{langue}.json").read_text(encoding="utf-8")))
    return clefs


def test_chaque_code_de_refus_a_son_libelle_dans_les_deux_langues() -> None:
    codes = _codes_de_refus()
    emis = (set(codes) | set(REFUS_INDIRECTS)) - set(REFUS_TRADUITS_AILLEURS)
    for langue in LANGUES:
        manquants = sorted(emis - _clefs_de_libelle(langue))
        assert not manquants, (
            f"{len(manquants)} codes de refus sans libellé en {langue}, qui s'afficheraient"
            " en clef brute sur l'écran :\n"
            + "\n".join(f"  {c} — {codes.get(c) or REFUS_INDIRECTS[c][0]}" for c in manquants)
        )


def test_les_refus_indirects_declares_existent_toujours_dans_les_sources() -> None:
    sources = "\n".join(f.read_text(encoding="utf-8") for f in SRC.rglob("*.py"))
    absents = [code for code, (_, fragment) in REFUS_INDIRECTS.items() if fragment not in sources]
    assert not absents, f"refus indirects déclarés mais introuvables dans les sources : {absents}"


def test_les_refus_traduits_ailleurs_le_sont_toujours() -> None:
    """Une dispense se périme : le composant qui la justifiait peut avoir changé.

    Sans ce contrôle, un code dispensé resterait dispensé après que l'écran a cessé de le
    reconnaître — et il s'afficherait en clef brute, que cette garde est censée empêcher.
    """
    manquants = [
        code
        for code, (fichier, fragment) in REFUS_TRADUITS_AILLEURS.items()
        if fragment not in (FRONT_SRC / fichier).read_text(encoding="utf-8")
    ]
    assert not manquants, f"dispenses périmées, le front ne reconnaît plus : {manquants}"


def test_le_releve_des_refus_trouve_bien_des_codes() -> None:
    # Même vert trompeur que pour les problèmes : un chemin devenu faux ferait porter les
    # tests ci-dessus sur un ensemble vide.
    codes = _codes_de_refus()
    assert len(codes) > 30, f"relevé suspect : {len(codes)} codes de refus seulement"
    assert "prise_de_main_requise" in codes, "le code d'une sous-classe a disparu du relevé"
