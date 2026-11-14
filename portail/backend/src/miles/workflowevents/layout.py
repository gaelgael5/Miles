"""Comment un type d'event se nomme, et ce qu'il peut désigner.

Un type d'event n'est plus un fichier depuis le 13/11/2026 : c'est un `DEFINE EVENT` de
l'artefact de son périmètre (`miles.workflowevents.dsl`), et le payload qu'il décrit est
un modèle de données ORDINAIRE. Ce module ne porte donc plus de chemins — il porte les
règles de nommage et de portée, qui sont celles de Miles et non celles du moteur.

Ces règles restent au PRODUIT, et c'est voulu : `miles_socle.parametrage.layout` porte ce
qu'un SECOND produit lit. Personne ne lit encore les déclarations hors du portail ; le
jour où un moteur de workflow tournera dans un module d'environnement, elles monteront au
socle. Pas avant : on n'invente pas un socle commun avant d'avoir deux usages à servir.
"""

from __future__ import annotations

import re

from miles.datamodels.layout import SHARED as SHARED
from miles.workflowevents.dsl import writable
from miles.workspaces.model import WorkspaceInputError

# Le nom d'un type d'event est PLUS ÉTROIT que celui d'un modèle, et c'est une MESURE, pas
# un excès de prudence : le DSL d'`urban-workflow` accepte `demande_soumise` et `demande2`
# mais REFUSE le tiret — `2:20: mismatched input '-' expecting ';'`, relevé le 11/11/2026
# sur urban-workflow 0.2.1. Un nom avec un tiret serait donc impossible à écrire dans un
# `DEFINE EVENT`. Le refus est ici, à la saisie, plutôt qu'au chargement d'un script.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")

# Les noms que le moteur se réserve — `__expired`, `__cancelReminderAction`, `$_result`,
# `$_reminder` — sont HORS D'ATTEINTE de `NAME_RE` : aucun ne commence par une minuscule
# ou un chiffre. Aucune liste noire à tenir, donc, et c'est mesuré et non supposé : la
# règle de nommage suffit à rendre la collision impossible. Les 48 mots réservés du DSL
# lui-même sont tous en majuscules, donc hors d'atteinte pour la même raison.


def checked_scope(scope: str) -> str:
    """Le périmètre d'une déclaration : « shared », ou un nom de domaine écrivable.

    Un domaine dont le nom porte un tiret existe légitimement — la règle des modèles
    l'admet — mais le DSL ne sait pas l'écrire, ni en `FRAGMENT NAME`, ni dans la
    référence `AS @domains.<domaine>.<modèle>`. Un tel périmètre ne peut donc pas porter
    de type d'event, et on le dit au moment du geste.
    """
    if scope == SHARED:
        return SHARED
    if not re.match(r"^[a-z0-9][a-z0-9_-]{0,62}$", scope):
        raise WorkspaceInputError("scope")
    if not writable(scope):
        raise WorkspaceInputError("scope_non_ecrivable")
    return scope


def checked_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise WorkspaceInputError("name")
    return name


def checked_model(scope: str, name: str) -> tuple[str, str]:
    """Le modèle qu'une déclaration désigne, vérifié écrivable par le DSL.

    Même raison que pour le périmètre : `AS @shared.mon-modele` est refusé par le moteur.
    Un modèle au nom à tiret reste un modèle parfaitement utilisable par un storage ou une
    source — il ne peut simplement pas devenir un type d'event sans être renommé.
    """
    if not writable(name):
        raise WorkspaceInputError("model_non_ecrivable")
    return scope, name


def visible(scope: str, target: tuple[str, str]) -> bool:
    """Un périmètre de domaine désigne un modèle de son domaine ou un transverse ; un
    périmètre transverse, un transverse seulement — il ne peut pas dépendre d'un domaine
    sans cesser d'être transverse. Même règle que les modèles entre eux."""
    target_scope, _ = target
    return target_scope == SHARED or (scope != SHARED and target_scope == scope)
