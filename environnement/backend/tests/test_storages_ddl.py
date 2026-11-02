from __future__ import annotations

import pytest

from environnement.storages.ddl import (
    IdentifierError,
    column_of,
    create_indexes,
    create_table,
    derivation,
    drop_column,
    index_name,
    is_ours,
    quoted,
    sql_type_of,
    statements_for,
)
from environnement.storages.model import Projection, StorageTable, TableIndex


def _projection(keys: tuple[str, ...], kind: str = "string") -> Projection:
    sql = sql_type_of(kind)
    assert sql is not None
    return Projection(column=column_of(keys), keys=keys, kind=kind, sql_type=sql)


def _table(*projections: Projection, indexes: tuple[TableIndex, ...] = ()) -> StorageTable:
    return StorageTable(
        storage="sites",
        label="Sites",
        schema="pudo",
        table="sites",
        model="pudo/site",
        projections=projections,
        indexes=indexes,
        keys=("$.Id",),
    )


class TestLesNoms:
    def test_un_nom_valide_est_cite(self) -> None:
        assert quoted("pudo") == '"pudo"'
        assert quoted("import-crm") == '"import-crm"'

    @pytest.mark.parametrize(
        "hostile",
        [
            'x"; drop table t; --',
            "x'y",
            "sites; delete from pudo.sites",
            "Sites",
            "_sites",
            "-sites",
            "si tes",
            "",
            "s" * 64,
        ],
    )
    def test_un_nom_hostile_ou_hors_regle_est_refuse_avant_tout_sql(self, hostile: str) -> None:
        """Refusé, et pas cité : PostgreSQL n'a pas de requête paramétrée pour du DDL.

        « Sites » et « _sites » ne sont pas hostiles, ils sont hors de la règle de
        nommage du dépôt — et une table qu'on n'a aucune raison de poser ne se pose pas.
        """
        with pytest.raises(IdentifierError):
            quoted(hostile)

    def test_un_nom_de_63_caracteres_passe_et_le_suivant_non(self) -> None:
        """La limite de PostgreSQL, qui TRONQUE en silence au-delà.

        Tenue par le motif lui-même (1 + 62), et par lui seul : la vérification de
        longueur écrite à côté ne pouvait jamais tirer, et elle a été retirée.
        """
        assert quoted("a" * 63) == '"' + "a" * 63 + '"'
        with pytest.raises(IdentifierError):
            quoted("a" * 64)


class TestLesColonnesProjetees:
    def test_un_chemin_devient_un_nom_de_colonne_lisible(self) -> None:
        assert column_of(("Contact", "Phone")) == "contact_phone"
        assert column_of(("Statut",)) == "statut"

    def test_un_nom_exotique_est_reduit_sans_laisser_de_souligne_en_bord(self) -> None:
        assert column_of(("code postal",)) == "code_postal"
        assert column_of(("adresse", "code-postal")) == "adresse_code_postal"
        assert column_of(("  x  ",)) == "x"

    def test_seul_ce_que_le_modele_prouve_est_type(self) -> None:
        assert sql_type_of("string") == "text"
        assert sql_type_of("integer") == "bigint"
        assert sql_type_of("number") == "numeric"
        assert sql_type_of("boolean") == "boolean"
        # Ce que le modèle ne dit pas, et les unions : en text.
        assert sql_type_of("valeur") == "text"
        assert sql_type_of("string|null") == "text"

    def test_un_conteneur_ne_fait_pas_une_colonne(self) -> None:
        """`#>>` en rendrait le JSON sérialisé, sur quoi aucun filtre n'a de sens."""
        assert sql_type_of("object") is None
        assert sql_type_of("array") is None

    def test_la_derivation_d_un_texte_n_est_pas_convertie(self) -> None:
        assert derivation(_projection(("Contact", "Phone"))) == 'objet #>> \'{"Contact","Phone"}\''

    def test_la_derivation_d_un_nombre_est_convertie_vers_le_type_du_modele(self) -> None:
        assert derivation(_projection(("Postes",), "integer")) == (
            "(objet #>> '{\"Postes\"}')::bigint"
        )

    def test_un_nom_de_propriete_a_guillemets_ou_apostrophe_est_echappe_deux_fois(self) -> None:
        """Le littéral de tableau, puis la chaîne SQL qui le porte.

        Le paramétrage vient du réseau : un nom de propriété est une valeur, et elle ne
        doit pas pouvoir refermer la chaîne qui la transporte.
        """
        assert derivation(_projection(('a"b',))) == 'objet #>> \'{"a\\"b"}\''
        assert derivation(_projection(("a'b",))) == "objet #>> '{\"a''b\"}'"
        assert derivation(_projection(("a\\b",))) == "objet #>> '{\"a\\\\b\"}'"


class TestLaTable:
    def test_la_table_porte_les_colonnes_fixes_et_les_derivees(self) -> None:
        sql = create_table(_table(_projection(("Statut",))))

        assert 'create table if not exists "pudo"."sites"' in sql
        assert '"objet" jsonb not null' in sql
        assert '"id" bigint generated always as identity primary key' in sql
        assert "\"origine\" text not null default 'import'" in sql
        assert '"statut" text generated always as (objet #>> \'{"Statut"}\') stored' in sql

    def test_la_creation_est_rejouable(self) -> None:
        """`if not exists` partout : servir deux fois la même version ne doit rien casser."""
        for sql in statements_for(_table(_projection(("Statut",)))):
            assert "if not exists" in sql

    def test_la_cle_fonctionnelle_porte_un_index_unique(self) -> None:
        """C'est lui qui fait tenir la réconciliation : une clé, un objet."""
        assert 'create unique index if not exists "sites__cle"' in create_indexes(_table())[0]

    def test_un_index_declare_porte_ses_colonnes_dans_l_ordre_declare(self) -> None:
        pays, code = _projection(("Pays",)), _projection(("CodePostal",))
        table = _table(pays, code, indexes=(TableIndex("geo", ("pays", "code_postal")),))

        assert create_indexes(table)[1] == (
            'create index if not exists "sites__geo" on "pudo"."sites" ("pays", "code_postal")'
        )

    def test_les_index_poses_ici_sont_reconnaissables_et_les_autres_intouchables(self) -> None:
        """Ce qui autorise à en supprimer : un index sans la marque est à quelqu'un d'autre."""
        assert is_ours("sites", index_name("sites", "geo"))
        assert not is_ours("sites", "sites_pkey")
        assert not is_ours("sites", "idx_pose_a_la_main")

    def test_retirer_une_colonne_derivee_ne_vise_que_la_colonne(self) -> None:
        sql = drop_column(_table(), "statut")

        assert sql == 'alter table "pudo"."sites" drop column if exists "statut"'
