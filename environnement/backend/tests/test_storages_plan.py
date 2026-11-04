from __future__ import annotations

from environnement.storages.model import (
    REFUSAL_TYPE_CHANGE,
    REFUSAL_UNEXPECTED_SHAPE,
    Projection,
    StorageRefusal,
    StorageTable,
    TableIndex,
)
from environnement.storages.plan import alignment, missing_fixed
from environnement.storages.store import ExistingColumn, ExistingIndex, ExistingTable

TEL = Projection("contact_phone", ("Contact", "Phone"), "string", "text")
POSTES = Projection("postes", ("Postes",), "integer", "bigint")
TABLE = StorageTable(
    storage="accounts",
    label="Accounts",
    schema="pudo",
    table="accounts",
    model="pudo/accounts",
    projections=(TEL,),
    indexes=(TableIndex("tel", ("contact_phone",)),),
    keys=("$.AccountId",),
)
FIXES = (
    ExistingColumn("id", "bigint", False),
    ExistingColumn("cle", "text", False),
    ExistingColumn("objet", "jsonb", False),
    ExistingColumn("empreinte", "bytea", False),
    ExistingColumn("origine", "text", False),
    ExistingColumn("vu_le", "timestamp with time zone", False),
    ExistingColumn("modifie_le", "timestamp with time zone", False),
    ExistingColumn("version_modele", "integer", False),
)


CLE = ExistingIndex("accounts__cle", ("cle",))
TEL_INDEX = ExistingIndex("accounts__tel", ("contact_phone",))


def _existe(
    *projetees: ExistingColumn, index: tuple[ExistingIndex, ...] = (CLE, TEL_INDEX)
) -> ExistingTable:
    return ExistingTable(columns=FIXES + projetees, indexes=index)


class TestLaFormeDeLaTable:
    def test_une_table_conforme_ne_manque_de_rien(self) -> None:
        assert missing_fixed(_existe()) is None

    def test_une_colonne_fixe_absente_est_nommee(self) -> None:
        sans_empreinte = ExistingTable(
            columns=tuple(c for c in FIXES if c.name != "empreinte"), indexes=()
        )

        assert missing_fixed(sans_empreinte) == "empreinte"

    def test_une_colonne_fixe_mal_typee_est_nommee_avec_son_type(self) -> None:
        """Signalé, jamais réparé : on ne sait pas ce que cette table porte."""
        autre = ExistingTable(
            columns=tuple(
                ExistingColumn(c.name, "text" if c.name == "objet" else c.sql_type, c.generated)
                for c in FIXES
            ),
            indexes=(),
        )

        assert missing_fixed(autre) == "objet:text"


class TestLAlignement:
    def test_une_table_deja_conforme_ne_demande_rien(self) -> None:
        plan = alignment(TABLE, _existe(ExistingColumn("contact_phone", "text", True)))

        assert plan == ([], False)

    def test_une_propriete_ajoutee_donne_une_colonne_et_la_base_bouge(self) -> None:
        voulue = StorageTable(**{**TABLE.__dict__, "projections": (TEL, POSTES)})

        plan = alignment(voulue, _existe(ExistingColumn("contact_phone", "text", True)))

        assert not isinstance(plan, StorageRefusal)
        instructions, bouge = plan
        assert bouge is True
        assert any("add column if not exists" in i and '"postes"' in i for i in instructions)

    def test_une_colonne_derivee_que_la_version_ne_declare_plus_est_retiree(self) -> None:
        """Sans perte : la colonne est une fonction de `objet`."""
        plan = alignment(
            TABLE,
            _existe(
                ExistingColumn("contact_phone", "text", True),
                ExistingColumn("contact_email", "text", True),
            ),
        )

        assert not isinstance(plan, StorageRefusal)
        instructions, bouge = plan
        assert bouge is True
        assert any('drop column if exists "contact_email"' in i for i in instructions)

    def test_une_colonne_de_donnees_du_meme_nom_fait_refuser_plutot_qu_ecraser(self) -> None:
        """Elle pourrait porter de la donnée propre, que la dérivation écraserait."""
        plan = alignment(TABLE, _existe(ExistingColumn("contact_phone", "text", False)))

        assert plan == StorageRefusal("accounts", REFUSAL_UNEXPECTED_SHAPE, "contact_phone")

    def test_un_changement_de_type_s_arrete_et_le_dit(self) -> None:
        """Réécrire la table sous verrou n'a pas été mesuré : on ne le paie pas en silence."""
        voulue = StorageTable(**{**TABLE.__dict__, "projections": (POSTES,)})

        plan = alignment(voulue, _existe(ExistingColumn("postes", "text", True)))

        assert plan == StorageRefusal("accounts", REFUSAL_TYPE_CHANGE, "postes:text->bigint")

    def test_un_index_manquant_est_cree_SANS_tolerance_et_fait_bouger_la_base(self) -> None:
        """Sans `if not exists` : cette tolérance se décide sur le NOM, donc un index de ce
        nom posé sur une autre table ferait taire la création, en silence."""
        plan = alignment(
            TABLE,
            _existe(ExistingColumn("contact_phone", "text", True), index=(CLE,)),
        )

        assert not isinstance(plan, StorageRefusal)
        instructions, bouge = plan
        assert bouge is True
        assert instructions == [
            'create index "accounts__tel" on "pudo"."accounts" ("contact_phone")'
        ]

    def test_un_index_declare_dont_les_colonnes_changent_est_refait(self) -> None:
        """Il garde son NOM : comparer les seuls noms l'aurait laissé en place, indexant
        ce que la version ne demande plus."""
        plan = alignment(
            TABLE,
            _existe(
                ExistingColumn("contact_phone", "text", True),
                index=(CLE, ExistingIndex("accounts__tel", ("cle",))),
            ),
        )

        assert not isinstance(plan, StorageRefusal)
        instructions, bouge = plan
        assert bouge is True
        # Retiré AVANT d'être reposé, sinon la création bute sur le nom.
        assert instructions == [
            'drop index if exists "pudo"."accounts__tel"',
            'create index "accounts__tel" on "pudo"."accounts" ("contact_phone")',
        ]

    def test_un_index_a_nous_que_la_version_ne_declare_plus_est_retire(self) -> None:
        plan = alignment(
            TABLE,
            _existe(
                ExistingColumn("contact_phone", "text", True),
                index=(CLE, TEL_INDEX, ExistingIndex("accounts__mail", ("contact_email",))),
            ),
        )

        assert not isinstance(plan, StorageRefusal)
        instructions, bouge = plan
        assert bouge is True
        assert any('drop index if exists "pudo"."accounts__mail"' in i for i in instructions)

    def test_un_index_pose_par_quelqu_un_d_autre_n_est_jamais_touche(self) -> None:
        plan = alignment(
            TABLE,
            _existe(
                ExistingColumn("contact_phone", "text", True),
                index=(
                    CLE,
                    TEL_INDEX,
                    ExistingIndex("accounts_pkey", ("id",)),
                    ExistingIndex("idx_a_la_main", ("cle",)),
                ),
            ),
        )

        assert not isinstance(plan, StorageRefusal)
        instructions, bouge = plan
        assert bouge is False
        assert not any("drop index" in i for i in instructions)
