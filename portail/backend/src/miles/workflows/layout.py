"""Où vit un script de workflow dans la branche, et comment il se nomme.

Un workflow est un script **complet** du DSL d'`urban-workflow`, par opposition aux
`FRAGMENT` de périmètre qu'écrit `miles.workflowevents.dsl`. Il vit à la RACINE de la
branche, sous `workflows/`, et non sous un périmètre : il `INCLUDE` PLUSIEURS périmètres
— le transverse et un ou plusieurs domaines —, donc le ranger sous `domains/<d>/`
prétendrait qu'il appartient à un domaine alors qu'il nomme les events de plusieurs.
L'artefact d'un périmètre, lui, est à la racine de SON périmètre précisément parce qu'il
ne décrit que celui-là.

Même emplacement et même raison que `transformations/` pour les chaînes (Gael,
22/10/2026) : une chaîne n'est pas davantage un objet de domaine, et le dépôt est déjà
propre à une application.

Ces règles restent au PRODUIT. `miles_socle.parametrage.layout` porte ce qu'un SECOND
produit lit, et personne ne lit encore ces scripts hors du portail : le jour où un moteur
de workflow tournera dans un module d'environnement, elles monteront au socle. Pas avant
— on n'invente pas un socle commun avant d'avoir deux usages à servir.
"""

from __future__ import annotations

import re

from miles.datamodels.layout import SHARED
from miles.workflowevents.dsl import SUFFIX as SUFFIX
from miles.workflowevents.dsl import writable
from miles.workspaces.model import WorkspaceInputError

ROOT = "workflows"
# Le MÊME suffixe que les artefacts de périmètre, et c'est délibéré : `load_directory`
# du moteur découvre les scripts par `glob`, fragments et scripts complets mêlés, et
# distingue les deux par `is_fragment` — jamais par l'extension. Une extension à part
# obligerait la transformation de publication à RENOMMER les fichiers, et un `INCLUDE`
# dont la cible a été renommée ne se résout plus. Importé de `workflowevents.dsl` plutôt
# que recopié : c'est la même décision, pas deux décisions qui se ressemblent.
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\{SUFFIX}$")

# Le nom d'un workflow : minuscules, chiffres et soulignés, et il COMMENCE PAR UNE LETTRE.
#
# Plus étroit que le nom d'un type d'event (`^[a-z0-9][a-z0-9_]…`), et c'est une mesure et
# non un excès : le `REGULAR_ID` du DSL est `[A-Za-z][A-Za-z0-9_]*`, donc un chiffre en
# tête est une erreur de PARSEUR, comme le tiret est une erreur de lexer. Admettre
# `[a-z0-9]` en tête faisait refuser `2` par `writable` — donc sous
# `name_non_ecrivable`, dont le message parle de mot réservé. Le nom était bien refusé,
# mais pour une raison fausse, et c'est la campagne du 16/11/2026 qui l'a montré.
#
# Ce nom devient à la fois le `NAME` du script et le nom de son fichier — voir
# `workflow_path`.
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def workflow_path(name: str) -> str:
    """Le fichier d'un workflow : `workflows/<nom>.wf`, nommé D'APRÈS son `NAME`.

    Rien n'`INCLUDE` un script complet, donc le nom du fichier serait libre côté moteur.
    Il porte quand même le `NAME` du script, pour deux raisons : la liste se construit
    alors sans ouvrir chaque fichier, et un fichier dont le nom ne dit pas ce qu'il
    déclare se fait renommer de travers par la première main qui passe dans git.
    """
    return f"{ROOT}/{name}{SUFFIX}"


def names_in(paths: list[str]) -> list[str]:
    """Les noms de workflow que ces chemins portent, triés."""
    return sorted(m["name"] for m in map(_FILE_RE.match, paths) if m is not None)


def checked_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise WorkspaceInputError("name")
    if not writable(name):
        # `writable` écarte en plus les 48 mots réservés du DSL, LUS du lexer installé.
        # Tous sont en majuscules, donc hors d'atteinte de `NAME_RE` — mais la garde reste
        # explicite : une montée du moteur pourrait en ajouter un en minuscules, et le
        # script deviendrait inchargeable sans que rien n'ait l'air faux.
        raise WorkspaceInputError("name_non_ecrivable")
    return name


def checked_against_scopes(name: str, domains: list[str]) -> str:
    """Refuse un workflow qui porterait le nom d'un périmètre de la branche.

    La transformation de publication rassemble `shared/shared.wf`, `domains/<d>/<d>.wf` et
    `workflows/<nom>.wf` dans UN SEUL répertoire, parce que c'est ce que
    `dsl.loader.load_directory` charge et qu'un `INCLUDE` désigne un nom de FICHIER.
    Dans ce répertoire plat, un workflow nommé `shared` et l'artefact du périmètre
    transverse deviennent le même fichier : l'un écraserait l'autre, et le périmètre
    perdu ne se signalerait que par des events introuvables au chargement.

    Refusé ICI, au geste, plutôt qu'à la publication : à la publication, le nom est déjà
    dans l'historique git et dans les `INCLUDE` qui le nomment.
    """
    if name == SHARED or name in domains:
        raise WorkspaceInputError("nom_de_perimetre")
    return name
