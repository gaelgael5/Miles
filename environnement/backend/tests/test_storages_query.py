from __future__ import annotations

import pytest

from environnement.storages.ddl import IdentifierError
from environnement.storages.model import Projection, StorageTable, TableIndex
from environnement.storages.query import (
    MAX_PAGE_SIZE,
    Criterion,
    FilterError,
    build,
    parse_criterion,
)

TABLE = StorageTable(
    storage="accounts",
    label="Accounts",
    schema="pudo",
    table="accounts",
    model="pudo/accounts",
    projections=(
        Projection("contact_phone", ("Contact", "Phone"), "string", "text"),
        Projection("postes", ("Postes",), "integer", "bigint"),
    ),
    indexes=(TableIndex("index-1", ("contact_phone",)),),
    keys=("$.AccountId",),
)


class TestLaLectureDUnCritere:
    def test_un_critere_se_lit_en_trois_parties(self) -> None:
        assert parse_criterion("contact_phone:eq:0102") == Criterion("contact_phone", "eq", "0102")

    def test_la_valeur_peut_porter_des_deux_points(self) -> None:
        """Une heure, une URL : la valeur est tout ce qui suit l'opérateur."""
        assert parse_criterion("vu:ge:2026-11-02T07:08:24").value == "2026-11-02T07:08:24"

    @pytest.mark.parametrize("raw", ["", "x", "x:eq", ":eq:v", "x::v"])
    def test_un_critere_malforme_est_refuse(self, raw: str) -> None:
        with pytest.raises(FilterError) as refus:
            parse_criterion(raw)
        assert refus.value.code == "critere_malforme"

    def test_un_operateur_hors_liste_est_refuse(self) -> None:
        """La liste est fermée : c'est elle qui empêche un fragment d'appelant d'entrer."""
        with pytest.raises(FilterError) as refus:
            parse_criterion("x:= 1 or 1=1 --:v")
        assert refus.value.code == "operateur_inconnu"


class TestLaRequete:
    def test_les_valeurs_partent_en_parametres_et_jamais_dans_le_texte(self) -> None:
        requete = build(TABLE, [Criterion("contact_phone", "eq", "0102'; drop table t; --")])

        assert "drop table" not in requete.sql
        assert '"contact_phone" = $1' in requete.sql
        assert requete.values == ("0102'; drop table t; --",)

    def test_une_propriete_non_declaree_est_refusee_et_nommee(self) -> None:
        """Pas de repli sur un parcours de table : c'est une erreur d'appel."""
        with pytest.raises(FilterError) as refus:
            build(TABLE, [Criterion("telephone", "eq", "x")])
        assert (refus.value.code, refus.value.detail) == ("propriete_non_filtrable", "telephone")

    def test_la_cle_fonctionnelle_est_filtrable_comme_les_autres(self) -> None:
        """La première chose qu'on cherche dans un storage, et elle a son index unique."""
        requete = build(TABLE, [Criterion("cle", "eq", "A-1")])

        assert '"cle" = $1' in requete.sql

    def test_un_nom_de_colonne_hostile_n_atteint_meme_pas_le_sql(self) -> None:
        hostile = StorageTable(
            **{
                **TABLE.__dict__,
                "projections": (Projection('x"; drop table t; --', ("X",), "string", "text"),),
            }
        )

        with pytest.raises(IdentifierError):
            build(hostile, [Criterion('x"; drop table t; --', "eq", "v")])

    def test_les_criteres_combines_rendent_l_intersection(self) -> None:
        requete = build(
            TABLE,
            [Criterion("contact_phone", "prefixe", "01"), Criterion("postes", "ge", "3")],
        )

        assert '"contact_phone" like $1 AND "postes" >= $2' in requete.sql
        assert requete.values == ("01%", "3")

    def test_un_prefixe_neutralise_les_jokers_de_la_valeur(self) -> None:
        """Sans quoi « 100% » chercherait « 100 suivi de n'importe quoi »."""
        requete = build(TABLE, [Criterion("contact_phone", "prefixe", "10%_a\\b")])

        assert requete.values == ("10\\%\\_a\\\\b%",)

    def test_un_prefixe_sur_une_colonne_non_textuelle_est_refuse(self) -> None:
        with pytest.raises(FilterError) as refus:
            build(TABLE, [Criterion("postes", "prefixe", "1")])
        assert refus.value.code == "prefixe_sur_valeur_non_textuelle"

    def test_le_tri_ne_porte_que_sur_une_colonne_declaree(self) -> None:
        with pytest.raises(FilterError) as refus:
            build(TABLE, [], sort="inconnue")
        assert refus.value.code == "propriete_non_triable"

    def test_l_ordre_est_total_pour_que_deux_pages_ne_se_recouvrent_pas(self) -> None:
        """`id` en dernier : deux objets de même valeur triée ont tout de même un ordre."""
        requete = build(TABLE, [], sort="postes", descending=True)

        assert requete.sql.count("ORDER BY") == 1
        assert 'ORDER BY "postes" DESC, "id" DESC' in requete.sql

    def test_sans_tri_demande_l_ordre_reste_celui_de_l_identite(self) -> None:
        assert 'ORDER BY "id" ASC' in build(TABLE, []).sql

    def test_la_pagination_saute_les_pages_precedentes(self) -> None:
        assert "LIMIT 10 OFFSET 20" in build(TABLE, [], page=3, page_size=10).sql

    def test_une_taille_de_page_demesuree_est_plafonnee(self) -> None:
        """Sans plafond, un appelant demanderait la table entière en une fois."""
        assert f"LIMIT {MAX_PAGE_SIZE} " in build(TABLE, [], page_size=10_000).sql

    def test_une_page_ou_une_taille_absurde_ne_produit_pas_de_sql_absurde(self) -> None:
        assert "LIMIT 1 OFFSET 0" in build(TABLE, [], page=0, page_size=0).sql

    def test_le_compte_porte_la_meme_clause_que_la_recherche(self) -> None:
        """Sinon le total afficherait autre chose que ce que la liste montre."""
        requete = build(TABLE, [Criterion("postes", "gt", "2")])

        assert requete.count_sql == ('SELECT count(*) FROM "pudo"."accounts" WHERE "postes" > $1')

    def test_la_selection_rend_l_objet_ses_dates_et_les_colonnes_projetees(self) -> None:
        requete = build(TABLE, [])

        for attendu in ('"cle"', '"objet"', '"vu_le"', '"modifie_le"', '"origine"'):
            assert attendu in requete.sql
        assert '"contact_phone"' in requete.sql
        assert '"postes"' in requete.sql
