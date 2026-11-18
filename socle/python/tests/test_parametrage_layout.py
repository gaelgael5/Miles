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

from miles_socle.parametrage.layout import (
    INBOUND,
    MODEL_RE,
    OUTBOUND,
    SHARED,
    model_id,
    model_path,
    target_of,
)


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


def test_un_modele_device_vit_sous_le_dossier_de_son_SENS() -> None:
    """L'emplacement validé par Gael le 23/10/2026, et le seul qui n'a pas d'étage
    `models/` : le dossier d'un sens ne contient que des modèles."""
    assert model_path(INBOUND, "transaction") == "devices/inbound/transaction.yaml"
    assert model_path(OUTBOUND, "parametrage") == "devices/outbound/parametrage.yaml"


def test_la_portee_d_un_modele_device_tient_en_UN_segment() -> None:
    """Discriminant de la décision, et pas une préférence d'écriture : la portée traverse
    `MODEL_RE` — par quoi un storage désigne un modèle — et l'URL `/{scope}/{name}`.
    Avec « devices/inbound », les deux auraient refusé la désignation."""
    assert MODEL_RE.match(f"{INBOUND}/transaction") is not None
    assert MODEL_RE.match("devices/inbound/transaction") is None


def test_l_identifiant_d_un_modele_device_porte_son_sens() -> None:
    assert model_id(INBOUND, "transaction") == "miles:/devices/inbound/transaction"
    assert model_id(OUTBOUND, "parametrage") == "miles:/devices/outbound/parametrage"


def test_une_reference_vers_un_modele_device_se_resout_vers_sa_portee() -> None:
    """L'aller-retour `model_id` → `target_of` : c'est lui qui fait qu'un `$ref` écrit par
    le portail est relu par le module d'environnement sur le même modèle."""
    for scope in (INBOUND, OUTBOUND):
        assert target_of(model_id(scope, "colis")) == (scope, "colis")


def test_un_sens_inconnu_ne_designe_aucun_modele() -> None:
    # La liste des sens est fermée : sans ce contrôle, `devices/<n_importe_quoi>/x`
    # résoudrait vers une portée que `model_path` ne saurait pas réécrire.
    assert target_of("miles:/devices/entrant/colis") is None
    assert target_of("miles:/devices/colis") is None
