"""Les chemins du paramétrage sont un CONTRAT entre produits : ce test les épingle.

`miles_socle.parametrage.layout` dit lui-même pourquoi il est au socle : « deux constantes
de même valeur dans deux produits auraient divergé au premier renommage fait d'un seul
côté, et le lecteur ne trouverait plus le fichier que l'écrivain a posé — sans que rien,
de part ni d'autre, paraisse faux ».

Jusqu'au 13/11/2026, **aucun test ne tenait cette valeur**. Mesuré ce jour-là en la
changeant : les 642 tests du socle sont restés verts. Le portail ÉCRIT l'arbre, le module
d'environnement le LIT (`storages/declarations.py`) — un renommage silencieux aurait rendu
les modèles introuvables chez le lecteur, sans erreur et sans trace.
"""

from __future__ import annotations

from miles_socle.parametrage.layout import SHARED, model_id, model_path, target_of


def test_un_modele_transverse_vit_sous_shared_models() -> None:
    assert model_path(SHARED, "personne") == "shared/models/personne.yaml"


def test_un_modele_de_domaine_vit_sous_son_domaine() -> None:
    assert model_path("livraison", "colis") == "domains/livraison/models/colis.yaml"


def test_l_identifiant_d_un_modele_ne_porte_PAS_le_dossier() -> None:
    """L'URI est indépendante de l'emplacement : le dossier a changé le 13/11/2026 et les
    `$ref` des déclarations existantes n'ont pas bougé. C'est ce qui rend le déplacement
    possible sans réécrire une seule déclaration de storage ou de source."""
    assert model_id(SHARED, "personne") == "miles:/shared/personne"
    assert model_id("livraison", "colis") == "miles:/domains/livraison/colis"


def test_une_reference_se_resout_vers_la_portee_et_le_nom() -> None:
    assert target_of("miles:/shared/personne") == (SHARED, "personne")
    assert target_of("miles:/domains/livraison/colis") == ("livraison", "colis")


def test_ce_qui_ne_designe_pas_un_modele_ne_se_resout_pas() -> None:
    assert target_of("miles:/events/shared/colis_recu") is None
    assert target_of("shared/personne") is None
