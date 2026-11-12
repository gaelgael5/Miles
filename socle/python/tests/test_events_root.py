from __future__ import annotations

from miles_socle.events.categories import CATEGORIES
from miles_socle.events.root import (
    COLUMN_OF_FIELD,
    ENGINE_ROOT_FIELDS,
    ENGINE_ROOT_SCHEMA,
    MILES_FIELDS,
    ROOT_FIELDS,
    ROOT_SCHEMA,
)


class TestLaRacineDeMilesSurchargeCelleDuMoteur:
    """« L'event doit être surchargé par un objet racine commun qui portera la catégorie et
    d'autres futures propriétés si ça arrive » (Gael, 12/11/2026).

    Ce que ces tests tiennent : la surcharge AJOUTE et ne touche à rien. Le jour où une
    propriété de nous porterait le nom d'une propriété du moteur, elle l'écraserait en
    silence — l'event validerait alors sur autre chose que ce que le moteur valide.
    """

    def test_la_racine_de_miles_porte_tous_les_champs_du_moteur(self) -> None:
        assert ENGINE_ROOT_FIELDS <= ROOT_FIELDS

    def test_elle_les_porte_a_l_identique(self) -> None:
        for nom, declaration in ENGINE_ROOT_SCHEMA["properties"].items():
            assert ROOT_SCHEMA["properties"][nom] == declaration, f"champ {nom}"

    def test_elle_n_ajoute_que_ce_que_MILES_FIELDS_declare(self) -> None:
        assert ROOT_FIELDS - ENGINE_ROOT_FIELDS == set(MILES_FIELDS)

    def test_aucun_ajout_de_miles_ne_recouvre_un_champ_du_moteur(self) -> None:
        # La garde qui compte : un `Category` côté moteur, demain, rendrait la surcharge
        # silencieuse. Ici elle devient un échec de test.
        assert set(MILES_FIELDS) & ENGINE_ROOT_FIELDS == set()

    def test_la_categorie_est_un_entier_enumere_derive_des_categories_declarees(self) -> None:
        """« On reste sur les numéros » (Gael, 12/11/2026) : c'est le numéro qui voyage.

        Et l'énumération est DÉRIVÉE de la liste des catégories, jamais recopiée : une
        catégorie ajoutée là-bas doit entrer ici toute seule, sinon le schéma refuserait
        une valeur que le code accepte. Ce test est ce qui tient cette dérivation.
        """
        categorie = ROOT_SCHEMA["properties"]["Category"]

        assert categorie["type"] == "integer"
        assert categorie["enum"] == [item.number for item in CATEGORIES]
        # Discriminant : sept catégories déclarées, donc sept valeurs — un `enum` figé à
        # six serait vert sur la seule comparaison de type.
        assert len(categorie["enum"]) == len(CATEGORIES)

    def test_la_racine_du_moteur_n_est_pas_modifiee_par_l_assemblage(self) -> None:
        # Assemblée par copie profonde : sans elle, ajouter `Category` à la racine de Miles
        # l'ajouterait AUSSI à la copie de l'amont, et la garde du portail la croirait
        # divergente — ou pire, ne la verrait plus.
        assert "Category" not in ENGINE_ROOT_SCHEMA["properties"]
        assert ENGINE_ROOT_SCHEMA["title"] == "urban-workflow base event"

    def test_la_categorie_n_a_pas_de_colonne_de_journal(self) -> None:
        """Délibéré : rien ne sait encore poser une valeur juste. Ce test tombera le jour où
        le catalogue de types déclarera les catégories, et c'est le bon moment pour y
        penser."""
        assert set(COLUMN_OF_FIELD) == ENGINE_ROOT_FIELDS
        assert "Category" not in COLUMN_OF_FIELD
