"""Ce que le produit ÉCRIT dans git, son propre diagnostic d'arborescence l'admet.

Cette garde naît d'un défaut réel, trouvé le 01/11/2026 sur une copie d'écran : la
référence de compte (story a3ece1e9) écrit `comptes/reference.yaml`, et `diagnose` le
rapportait en « emplacement inattendu ». Conséquence, invisible à toute suite existante :
**aucune version n'était enregistrable** sur une branche ayant une référence de compte,
et le message n'accusait pas le vrai coupable.

La cause n'est pas l'oubli d'une ligne, c'est que le nom vit à DEUX endroits — dans le
module métier qui écrit, et dans la couche git qui juge. On ne peut pas les fondre : la
couche git ne doit dépendre d'aucun module métier. On les tient donc par ce test, comme
la frontière entre produits est tenue par `tests/` à la racine.
"""

from __future__ import annotations

import json

import pytest

from miles.accounts.layout import PATH as ACCOUNTS_PATH
from miles.chains.layout import ROOT as CHAINS_ROOT
from miles.git.worktree import INITIAL_MANIFEST, MANIFEST, diagnose
from miles.sources.layout import ROOT as SOURCES_ROOT
from miles.storages.layout import ROOT as STORAGES_ROOT

MANIFEST_TEXT = json.dumps(INITIAL_MANIFEST)


def _unexpected(*paths: str) -> list[str]:
    return diagnose([MANIFEST, *paths], MANIFEST_TEXT).unexpected


def test_la_reference_de_compte_est_a_un_emplacement_admis() -> None:
    """Le défaut du 31/10/2026, et le test qui l'aurait vu le jour même.

    Le chemin est IMPORTÉ du module qui l'écrit, jamais recopié : recopié, il resterait
    vrai dans ce fichier pendant que le produit en emploierait un autre.
    """
    assert _unexpected(ACCOUNTS_PATH) == []


@pytest.mark.parametrize("root", [CHAINS_ROOT, SOURCES_ROOT, STORAGES_ROOT])
def test_chaque_racine_declaree_par_un_module_est_admise(root: str) -> None:
    """Toute la famille, et pas le seul cas qui a mordu.

    Un module qui déclare une racine git et oublie de l'ouvrir dans `_allowed` rend la
    branche non figeable. Les racines sont importées de leurs modules : en ajouter une
    sans l'admettre fait rougir ici, au lieu de se découvrir sur un écran six mois plus
    tard.
    """
    assert _unexpected(f"{root}/quelque-chose.yaml") == []


def test_un_emplacement_vraiment_inattendu_reste_rapporte() -> None:
    # Sans ce contrôle, un `_allowed` qui dirait oui à tout passerait les tests ci-dessus
    # — et la garde entière ne mesurerait plus rien.
    assert _unexpected("au-hasard/fichier.yaml") == ["au-hasard/fichier.yaml"]


def test_un_second_fichier_sous_comptes_est_refuse() -> None:
    """Une branche a UNE référence de compte, pas une liste : la règle tient au chemin.

    Ouvrir `comptes/` en entier aurait corrigé le défaut en en créant un autre — des
    fichiers que rien ne lit, et que rien ne signalerait.
    """
    assert _unexpected("comptes/autre.yaml") == ["comptes/autre.yaml"]
