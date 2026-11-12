from __future__ import annotations

from typing import Any, ClassVar

import pytest

from miles_socle.events.catalog import (
    CatalogError,
    DeclaredEvent,
    EventCatalog,
    EventShape,
    introduced_by,
)
from miles_socle.events.categories import of_number
from miles_socle.events.model import EventAuthor, EventError, NewEvent, ObjectRef

BACKOFFICE = of_number(0)
AUTHOR = EventAuthor("local", "admin")
# Un bloc réaliste, pris sur un producteur réel du portail : `{storage, commit, branch}`.
BLOC: dict[str, Any] = {
    "type": "object",
    "properties": {
        "storage": {"type": "string", "minLength": 1},
        "commit": {"type": "string", "minLength": 1},
        "branch": {"type": "string"},
    },
    "required": ["storage", "commit"],
}


def _declared(**overrides: Any) -> DeclaredEvent:
    champs: dict[str, Any] = {
        "name": "storage.declared",
        "label": "Storage déclaré",
        "category": BACKOFFICE,
        "block": BLOC,
    }
    champs.update(overrides)
    return DeclaredEvent(**champs)


def _event(properties: dict[str, Any], event_type: str = "storage.declared") -> NewEvent:
    return NewEvent(event_type, (ObjectRef("workspace", "w1"),), AUTHOR, properties)


class TestCeQueLeCatalogueRefuseAuChargement:
    """Au CHARGEMENT, et non au premier event : un catalogue faux doit faire tomber le
    démarrage du produit, pas un geste métier choisi au hasard par le trafic."""

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"name": "Storage Declared"}, "identifiant de type d'event invalide"),
            ({"label": "   "}, "sans libellé"),
            ({"block": {"type": "array"}}, "n'est pas un schéma d'objet"),
            ({"block": {"properties": {"a": {}}}}, "n'est pas un schéma d'objet"),
        ],
        ids=["nom-majuscules", "libelle-blanc", "bloc-tableau", "bloc-sans-type"],
    )
    def test_une_declaration_malformee_est_refusee(
        self, overrides: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(CatalogError, match=message):
            EventCatalog([_declared(**overrides)])

    def test_un_tiret_est_admis_ici_alors_que_le_DSL_le_refuse(self) -> None:
        """Mesuré le 12/11/2026, et la nuance compte : la règle de nommage du JOURNAL
        (`^[a-z][a-z0-9_.-]{0,99}$`) admet le tiret, tandis que le DSL d'urban-workflow le
        refuse dans un nom d'event (`mismatched input '-' expecting ';'`). Les deux règles
        coexistent délibérément — le catalogue en code ne passe jamais par le DSL, celui du
        dépôt du workspace si. Ce test est là pour qu'on ne les aligne pas « pour faire
        propre » : ce serait durcir l'un sans raison, ou casser l'autre.
        """
        catalogue = EventCatalog([_declared(name="storage-declared")])

        assert catalogue.names() == {"storage-declared"}

    @pytest.mark.parametrize("champ", ["Name", "Uuid", "ExternalId", "Category"])
    def test_un_bloc_qui_redeclare_un_champ_de_la_racine_est_refuse_en_le_nommant(
        self, champ: str
    ) -> None:
        """La racine vit en colonnes. Un type qui la redéclare créerait une seconde valeur
        pour le même champ — et `Category` est discriminant : c'est un ajout de Miles, donc
        le refus doit porter sur la racine de Miles et pas seulement sur celle du moteur."""
        bloc = {"type": "object", "properties": {champ: {"type": "string"}, "a": {}}}

        with pytest.raises(CatalogError, match=f"racine : \\['{champ}'\\]"):
            EventCatalog([_declared(block=bloc)])

    def test_un_schema_de_bloc_invalide_est_refuse_en_disant_pourquoi(self) -> None:
        bloc = {"type": "object", "properties": {"a": {"type": "chaine"}}}

        with pytest.raises(CatalogError, match="schéma de bloc invalide"):
            EventCatalog([_declared(block=bloc)])

    def test_deux_types_de_meme_identifiant_sont_refuses(self) -> None:
        with pytest.raises(CatalogError, match="déclaré deux fois"):
            EventCatalog([_declared(), _declared(label="Un autre libellé")])


class TestLaValidationDuBloc:
    """Le point du ticket : le refus NOMME la propriété fautive."""

    CATALOGUE: ClassVar[EventCatalog] = EventCatalog([_declared()])

    def test_un_bloc_conforme_passe(self) -> None:
        self.CATALOGUE.check_event(_event({"storage": "colis", "commit": "abc", "branch": "dev"}))

    def test_une_propriete_obligatoire_absente_est_nommee(self) -> None:
        with pytest.raises(EventError, match="commit"):
            self.CATALOGUE.check_event(_event({"storage": "colis"}))

    def test_une_propriete_du_mauvais_type_est_nommee_par_son_chemin(self) -> None:
        with pytest.raises(EventError, match=r"\$\.commit"):
            self.CATALOGUE.check_event(_event({"storage": "colis", "commit": 42}))

    def test_le_refus_ne_dit_pas_seulement_schema_invalide(self) -> None:
        """Ce qui distingue un refus qu'on corrige d'un refus qu'on va relire dans les
        journaux. Éprouvé sur le message lui-même, pas sur le type d'exception."""
        with pytest.raises(EventError) as capture:
            self.CATALOGUE.check_event(_event({"storage": "", "commit": "abc"}))

        message = str(capture.value)
        assert "storage" in message
        assert "non conforme" in message

    def test_un_type_inconnu_est_refuse_en_le_nommant(self) -> None:
        with pytest.raises(EventError, match=r"inconnu du catalogue : 'storage\.deleted'"):
            self.CATALOGUE.check_event(_event({"storage": "c", "commit": "a"}, "storage.deleted"))

    def test_un_catalogue_vide_ne_laisse_rien_passer(self) -> None:
        # Fail closed : c'est l'état voulu d'un produit qui n'a rien déclaré.
        with pytest.raises(EventError, match="inconnu du catalogue"):
            EventCatalog().check_event(_event({}))

    def test_le_catalogue_rend_ce_qu_il_porte(self) -> None:
        assert self.CATALOGUE.names() == {"storage.declared"}
        declare = self.CATALOGUE.of("storage.declared")
        assert (declare.label, declare.category.number) == ("Storage déclaré", 0)


class TestCeQueLeProduitEtLeJournalAjOUTENT:
    """Deux mesures du 12/11/2026, chacune invalidante si elle avait été ratée."""

    FERME: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"slug": {"type": "string"}},
        "additionalProperties": False,
    }

    def test_un_meme_module_prend_la_categorie_du_produit_qui_l_introduit(self) -> None:
        """Les modules du socle sont produits par les trois produits. `culture.activated`
        est `backoffice-configuration` au portail et `backoffice-enrolement` à
        l'enrôlement — une seule déclaration, deux catégories."""
        partage = (EventShape("culture.activated", "Culture activée", BLOC),)

        au_portail = introduced_by(of_number(0), partage)
        a_l_enrolement = introduced_by(of_number(1), partage)

        assert au_portail[0].category.slug == "backoffice-configuration"
        assert a_l_enrolement[0].category.slug == "backoffice-enrolement"
        assert au_portail[0].label == a_l_enrolement[0].label

    def test_un_bloc_ferme_accepte_quand_meme_la_cle_d_api_que_le_journal_ajoute(
        self,
    ) -> None:
        """LE piège : le journal ajoute `via_api_key` au bloc quand l'auteur agit par une
        clé d'API. Sans cette tolérance, un type qui ferme son bloc refuserait TOUS les
        events écrits par la surface MCP — un défaut sans rapport avec ce qu'il déclare.
        """
        catalogue = EventCatalog([_declared(block=self.FERME)])

        catalogue.check_event(_event({"slug": "pat-forge", "via_api_key": "k-1"}))

    def test_un_bloc_ferme_refuse_toujours_une_propriete_inconnue(self) -> None:
        """Discriminant : la tolérance porte sur les DEUX clefs du journal, pas sur
        n'importe quoi — sinon fermer un bloc ne voudrait plus rien dire."""
        catalogue = EventCatalog([_declared(block=self.FERME)])

        with pytest.raises(EventError, match="coquille"):
            catalogue.check_event(_event({"slug": "pat-forge", "coquille": "x"}))
