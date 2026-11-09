from __future__ import annotations

from miles_socle.parametrage.storages import (
    Expiry,
    Index,
    names_in,
    read_storage,
    storage_path,
)

DECLARATION = """
nom: "accounts"
libelle: "Accounts"
modele: "pudo/accounts"
cle:
  - "$.AccountId"
index:
  - nom: "index-1"
    colonnes:
      - "$.Contact.Phone"
"""


def test_une_declaration_se_relit_entierement() -> None:
    doc = read_storage(DECLARATION)

    assert doc is not None
    assert (doc.name, doc.label, doc.model) == ("accounts", "Accounts", "pudo/accounts")
    assert doc.keys == ("$.AccountId",)
    assert doc.indexes == (Index("index-1", ("$.Contact.Phone",)),)


def test_l_ancienne_forme_indexables_se_convertit_en_index_d_une_colonne() -> None:
    """Déclarations écrites avant le 24/10/2026 : la conversion est exacte et sans perte."""
    doc = read_storage(
        'nom: "s"\nlibelle: "S"\nmodele: "d/m"\ncle: ["$.Id"]\n'
        'indexables:\n  - nom: "i"\n    jpath: "$.Statut"\n'
    )

    assert doc is not None
    assert doc.indexes == (Index("i", ("$.Statut",)),)


def test_les_deux_formes_a_la_fois_sont_refusees() -> None:
    """On ne devine pas laquelle fait foi."""
    assert (
        read_storage(
            'nom: "s"\nlibelle: "S"\nmodele: "d/m"\ncle: ["$.Id"]\nindex: []\nindexables: []\n'
        )
        is None
    )


def test_un_fichier_absent_illisible_ou_d_une_autre_forme_ne_rend_rien() -> None:
    assert read_storage(None) is None
    assert read_storage("nom: [") is None
    assert read_storage('nom: "s"\ninconnu: 1\n') is None
    # Sans clé, ce n'est pas une déclaration de storage.
    assert read_storage('nom: "s"\nlibelle: "S"\nmodele: "d/m"\n') is None


def test_les_noms_viennent_des_fichiers_du_repertoire_et_sont_ordonnes() -> None:
    paths = ["storages/sites.yaml", "autre/x.yaml", "storages/accounts.yaml", "storages/a/b.yaml"]

    assert names_in(paths) == ["accounts", "sites"]
    assert storage_path("accounts") == "storages/accounts.yaml"


PEREMPTION = """
nom: "sites"
libelle: "Sites"
modele: "pudo/site"
cle:
  - "$.Id"
index:
  - nom: "fin-activite"
    colonnes:
      - "$.EndOfActivity"
peremption:
  - propriete: "$.EndOfActivity"
    delai_jours: 10
"""


def test_une_regle_de_peremption_se_relit_avec_sa_propriete_et_son_delai() -> None:
    doc = read_storage(PEREMPTION)

    assert doc is not None
    assert doc.expiries == (Expiry("$.EndOfActivity", 10),)


def test_une_declaration_sans_peremption_n_en_porte_aucune() -> None:
    """L'absence de règle est le défaut : un storage sans règle ne se nettoie pas."""
    doc = read_storage(DECLARATION)

    assert doc is not None
    assert doc.expiries == ()


def test_une_peremption_dont_le_delai_n_est_pas_un_entier_ne_rend_rien() -> None:
    # Un booléen est un entier en Python, jamais un délai : il est refusé comme le reste.
    for delai in ('"10"', "true", "10.5", "null"):
        assert (
            read_storage(
                'nom: "s"\nlibelle: "S"\nmodele: "d/m"\ncle: ["$.Id"]\n'
                f'peremption:\n  - propriete: "$.Fin"\n    delai_jours: {delai}\n'
            )
            is None
        ), delai


def test_une_peremption_sans_propriete_ou_mal_formee_ne_rend_rien() -> None:
    for regle in (
        "  - delai_jours: 10",
        '  - propriete: "$.Fin"',
        "  bidon: 1",
        '  - "$.Fin"',
        # Une clé mal orthographiée ne se laisse pas passer : la règle serait inerte,
        # et on croirait qu'elle protège.
        '  - propriete: "$.Fin"\n    delai_jour: 10',
    ):
        assert (
            read_storage(
                f'nom: "s"\nlibelle: "S"\nmodele: "d/m"\ncle: ["$.Id"]\nperemption:\n{regle}\n'
            )
            is None
        ), regle
