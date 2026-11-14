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
from miles.workflowevents.dsl import fragment_path

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


@pytest.mark.parametrize("scope", ["shared", "livraison"])
def test_l_artefact_de_declaration_d_un_perimetre_est_admis(scope: str) -> None:
    """Le défaut du 31/10/2026, dans sa forme du 14/11/2026.

    L'artefact des types d'event est un FICHIER à la racine d'un périmètre, là où le
    diagnostic n'attendait que des dossiers de rubriques. Sans son admission, chaque
    déclaration écrite rendait la branche non figeable — et le message aurait accusé
    l'arborescence, pas la déclaration. Le chemin est IMPORTÉ du module qui l'écrit :
    recopié, il resterait vrai ici pendant que le produit en emploierait un autre.
    """
    assert _unexpected(fragment_path(scope)) == []


def test_un_wf_qui_ne_porte_pas_le_nom_de_son_perimetre_reste_rapporte() -> None:
    """Le nom du FICHIER est la clef d'`INCLUDE` du moteur (`load_directory` indexe les
    fragments par chemin complet ET par nom de fichier seul) : deux périmètres portant le
    même nom de fichier s'éclipseraient dans cet index, le dernier chargé gagnant, en
    silence. D'où un seul nom admis par périmètre, et pas « tout `.wf` ».
    """
    assert _unexpected("shared/referentiel.wf") == ["shared/referentiel.wf"]
    assert _unexpected("domains/livraison/referentiel.wf") == ["domains/livraison/referentiel.wf"]


@pytest.mark.parametrize(
    "path",
    ["shared/messages/.gitkeep", "shared/events/.gitkeep", "domains/livraison/events/.gitkeep"],
)
def test_le_marqueur_d_une_rubrique_disparue_ne_bloque_pas_une_version(path: str) -> None:
    """Défaut mesuré le 14/11/2026 en relisant le diagnostic, et jamais livré.

    Le squelette d'une branche créait `shared/events/.gitkeep` ; la conversion ne déplace
    que ce qui porte du CONTENU, donc ce marqueur survit à la conversion. Sans cette
    tolérance il devenait un « emplacement inattendu » : toute branche ouverte avant le
    renommage cessait d'être figeable, et aucun geste ne la réparait — la conversion,
    elle, répondait « rien à faire ». Un marqueur ne porte aucun paramétrage.
    """
    assert _unexpected(path) == []


@pytest.mark.parametrize(
    "path", ["shared/events/colis_recu.yaml", "domains/livraison/messages/colis.yaml"]
)
def test_un_FICHIER_sous_une_rubrique_disparue_reste_rapporte(path: str) -> None:
    # Discriminant : c'est ce rapport qui envoie convertir. Tolérer la rubrique entière
    # aurait fait cohabiter deux rangements, dont un que plus rien ne lit.
    assert _unexpected(path) == [path]
