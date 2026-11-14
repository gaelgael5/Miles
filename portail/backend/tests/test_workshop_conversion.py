"""La disposition du dépôt : détectée, et jamais convertie toute seule.

Ce module décide du refus d'ouverture de toutes les branches de tous les workspaces : il
est éprouvé sur des listes de chemins, sans git ni disque.

Le nom de l'ANCIEN dossier est composé (`_VIEUX`) plutôt qu'écrit en clair, et ce n'est
pas une coquetterie : un renommage automatique du dépôt — celui qui a produit cette
conversion — l'aurait réécrit ici aussi, et ce fichier aurait cessé d'éprouver ce qu'il
éprouve. C'est arrivé le 13/11/2026, pendant la livraison.
"""

from __future__ import annotations

from typing import ClassVar

from miles.workshop.conversion import A_JOUR, ANCIENNE, MELANGEE, layout_of


def _moves(paths: list[str]) -> dict[str, str]:
    return {m.source: m.target for m in layout_of(paths).moves}


_VIEUX = "mess" + "ages"
ANCIEN_DEPOT = [
    f"shared/{_VIEUX}/personne.yaml",
    f"shared/{_VIEUX}/personne.meta.yaml",
    f"domains/livraison/{_VIEUX}/colis.yaml",
    "contracts/.gitkeep",
]
NOUVEAU_DEPOT = [
    "shared/models/personne.yaml",
    "shared/models/personne.meta.yaml",
    "domains/livraison/models/colis.yaml",
    "contracts/.gitkeep",
]


def test_un_depot_neuf_est_a_jour() -> None:
    assert layout_of(NOUVEAU_DEPOT).kind == A_JOUR
    assert layout_of(NOUVEAU_DEPOT).refusal is None


def test_un_depot_sans_aucun_modele_est_a_jour() -> None:
    """Une branche neuve dont le squelette n'a que des `.gitkeep` ne se fait pas refuser."""
    assert layout_of(["contracts/.gitkeep", "sources/.gitkeep"]).kind == A_JOUR


def test_un_depot_ancien_est_refuse_en_nommant_son_motif() -> None:
    layout = layout_of(ANCIEN_DEPOT)
    assert layout.kind == ANCIENNE
    assert layout.refusal == "disposition_ancienne"


def test_la_conversion_deplace_aussi_les_metadonnees() -> None:
    """La version d'un modèle vit dans `<nom>.meta.yaml` : la laisser derrière ferait
    repartir tous les modèles convertis sans version."""
    assert (
        _moves(ANCIEN_DEPOT)[f"shared/{_VIEUX}/personne.meta.yaml"]
        == "shared/models/personne.meta.yaml"
    )


def test_la_conversion_porte_sur_les_transverses_et_les_domaines() -> None:
    moves = _moves(ANCIEN_DEPOT)
    assert moves[f"shared/{_VIEUX}/personne.yaml"] == "shared/models/personne.yaml"
    assert moves[f"domains/livraison/{_VIEUX}/colis.yaml"] == "domains/livraison/models/colis.yaml"


def test_la_conversion_ne_touche_rien_hors_du_dossier_des_modeles() -> None:
    """`contracts/` et les autres rubriques ne bougent pas : elles n'ont jamais changé."""
    deplaces = set(_moves(ANCIEN_DEPOT))
    assert "contracts/.gitkeep" not in deplaces


def test_un_modele_portant_le_nom_de_l_ancien_dossier_garde_son_nom() -> None:
    """Seul le SEGMENT de dossier est remplacé. Un remplacement de chaîne naïf
    renommerait aussi le fichier, et le modèle deviendrait introuvable."""
    moves = _moves([f"shared/{_VIEUX}/{_VIEUX}.yaml"])
    assert moves[f"shared/{_VIEUX}/{_VIEUX}.yaml"] == f"shared/models/{_VIEUX}.yaml"


def test_un_depot_a_moitie_converti_est_refuse_sans_deviner() -> None:
    """Conversion interrompue, ou fusion d'une branche convertie avec une qui ne l'est
    pas : un modèle des deux côtés n'a pas de bonne réponse automatique."""
    layout = layout_of([*ANCIEN_DEPOT, *NOUVEAU_DEPOT])
    assert layout.kind == MELANGEE
    assert layout.refusal == "disposition_melangee"
    assert layout.moves == ()


def test_un_dossier_de_meme_nom_ailleurs_dans_l_arbre_ne_declenche_rien() -> None:
    """L'ancien nom ne désigne un dossier de modèles que sous `shared/` ou `domains/<d>/`."""
    assert layout_of([f"transformations/{_VIEUX}/etape.yaml"]).kind == A_JOUR


def test_un_squelette_rafraichi_sur_un_depot_ancien_reste_convertible() -> None:
    """Le squelette d'une branche crée `shared/models/.gitkeep`. Compter ce marqueur
    comme un contenu rendrait le dépôt « mélangé », donc refusé — et refusé SANS issue,
    puisque la conversion refuse elle aussi un dépôt mélangé. Mesuré le 13/11/2026 en
    montant le test d'intégration : c'est exactement ce qui arrivait."""
    layout = layout_of(
        [*ANCIEN_DEPOT, "shared/models/.gitkeep", "domains/livraison/models/.gitkeep"]
    )
    assert layout.kind == ANCIENNE
    assert layout.refusal == "disposition_ancienne"


def test_le_marqueur_de_l_ancien_dossier_est_deplace_lui_aussi() -> None:
    """Sinon l'ancien dossier survit à sa conversion, et le dépôt reste « ancien » pour
    toujours : le `.gitkeep` seul suffirait à le faire refuser au prochain passage."""
    moves = _moves([f"shared/{_VIEUX}/colis.yaml", f"shared/{_VIEUX}/.gitkeep"])
    assert moves[f"shared/{_VIEUX}/.gitkeep"] == "shared/models/.gitkeep"


def test_un_ancien_dossier_qui_n_a_plus_que_son_marqueur_est_a_jour() -> None:
    """Rien à convertir : un dossier vide n'est pas une ancienne disposition, et refuser
    là ne mènerait à rien — la conversion ne déplacerait aucun modèle."""
    assert layout_of([f"shared/{_VIEUX}/.gitkeep", "shared/models/colis.yaml"]).kind == A_JOUR


class TestLesExEvents:
    """`events/` a rejoint `models/` le 14/11/2026 : un type d'event n'est plus un fichier.

    Ce que ces tests tiennent, et que le déplacement de `messages/` ne tenait pas : un
    ex-event ne fait pas que changer de dossier, il doit être DÉCLARÉ. Sans déclaration,
    la conversion perdrait l'information qui distinguait un event d'un modèle, et personne
    ne saurait la retrouver.
    """

    DEPOT: ClassVar[list[str]] = [
        "shared/events/colis_recu.yaml",
        "shared/events/colis_recu.meta.yaml",
        "domains/livraison/events/scan.yaml",
        "shared/models/personne.yaml",
        "shared/models/.gitkeep",
    ]

    def test_un_depot_qui_a_des_events_est_ancien(self) -> None:
        assert layout_of(self.DEPOT).kind == ANCIENNE

    def test_models_et_events_cote_a_cote_ne_font_PAS_un_depot_melange(self) -> None:
        """Les deux ont légitimement cohabité du 11/11 au 14/11/2026 — c'étaient deux
        rubriques du squelette. Les compter ensemble aurait rendu « mélangé » tout dépôt
        ouvert dans cette fenêtre, donc refusé SANS issue, puisque la conversion refuse
        elle aussi un dépôt mélangé. C'est le piège du `.gitkeep`, en plus large."""
        assert layout_of(self.DEPOT).refusal == "disposition_ancienne"

    def test_un_event_devient_un_modele_du_meme_perimetre(self) -> None:
        moves = _moves(self.DEPOT)

        assert moves["shared/events/colis_recu.yaml"] == "shared/models/colis_recu.yaml"
        assert moves["domains/livraison/events/scan.yaml"] == "domains/livraison/models/scan.yaml"

    def test_chaque_ex_event_est_a_declarer_avec_sa_portee(self) -> None:
        assert layout_of(self.DEPOT).event_types == (
            ("livraison", "scan"),
            ("shared", "colis_recu"),
        )

    def test_les_metadonnees_d_un_event_ne_sont_pas_un_event_a_declarer(self) -> None:
        """Discriminant : sans la règle, `colis_recu.meta` serait déclaré comme un type
        d'event, et le moteur chercherait un modèle qui n'existe pas."""
        declares = [m.event for m in layout_of(self.DEPOT).moves if m.event is not None]

        assert ("shared", "colis_recu.meta") not in declares
        assert len(declares) == 2

    def test_un_nom_deja_pris_par_un_modele_arrete_la_conversion(self) -> None:
        """On n'écrase pas : les deux documents sont dans la forge, et c'est là qu'un
        humain choisit lequel garder."""
        layout = layout_of(["shared/events/personne.yaml", "shared/models/personne.yaml"])

        assert layout.conflicts == ("shared/models/personne.yaml",)

    def test_un_depot_sans_conflit_n_en_rapporte_aucun(self) -> None:
        assert layout_of(self.DEPOT).conflicts == ()

    def test_un_dossier_events_qui_n_a_plus_que_son_marqueur_est_a_jour(self) -> None:
        assert layout_of(["shared/events/.gitkeep", "shared/models/colis.yaml"]).kind == A_JOUR
