from __future__ import annotations

from miles_socle.parametrage.sources import (
    DEFAULT_WRITE_BATCH,
    EntryModes,
    names_in,
    read_source,
    source_path,
)

DECLARATION = """
nom: "comptes-pudo"
libelle: "Comptes PUDO"
storage: "accounts"
entrees:
  - type: "web"
    modele_source: "pudo/compte-partenaire"
    chaine: "compte-vers-account"
    modes:
      element: true
      tableau: true
      fichier: false
    decoupage: ""
    transaction_unifiee: false
    lot_ecriture: 250
"""


def test_une_declaration_se_relit_entierement() -> None:
    doc = read_source(DECLARATION)

    assert doc is not None
    assert (doc.name, doc.label, doc.storage) == ("comptes-pudo", "Comptes PUDO", "accounts")
    assert len(doc.entries) == 1
    entree = doc.entries[0]
    assert (entree.kind, entree.source_model, entree.chain) == (
        "web",
        "pudo/compte-partenaire",
        "compte-vers-account",
    )
    assert entree.modes == EntryModes(element=True, batch=True, file=False)
    assert (entree.split, entree.unified_transaction, entree.write_batch) == ("", False, 250)


def test_un_mode_absent_vaut_faux_plutot_que_d_etre_devine() -> None:
    """Un mode non déclaré n'est pas exposé : le point d'entrée le refusera."""
    doc = read_source(
        'nom: "s"\nlibelle: "S"\nstorage: "st"\n'
        'entrees:\n  - type: "web"\n    modele_source: "d/m"\n    chaine: "c"\n'
        "    modes:\n      fichier: true\n"
    )

    assert doc is not None
    assert doc.entries[0].modes == EntryModes(element=False, batch=False, file=True)
    # Le découpage absent vaut vide : son absence se juge au diagnostic de saisie, qui
    # l'exige quand le mode fichier est coché — pas à la lecture du fichier.
    assert doc.entries[0].split == ""


def test_un_lot_d_ecriture_absent_prend_le_defaut_et_un_booleen_est_refuse() -> None:
    """Un booléen n'est pas un entier, même en Python : `True` ne vaut pas « 1 lecture »."""
    gabarit = (
        'nom: "s"\nlibelle: "S"\nstorage: "st"\n'
        'entrees:\n  - type: "web"\n    modele_source: "d/m"\n    chaine: "c"\n'
        "    modes:\n      element: true\n"
    )
    doc = read_source(gabarit)

    assert doc is not None
    assert doc.entries[0].write_batch == DEFAULT_WRITE_BATCH
    assert read_source(gabarit + "    lot_ecriture: true\n") is None


def test_une_entree_sans_liste_ou_a_clef_inconnue_ne_rend_rien() -> None:
    assert read_source(None) is None
    assert read_source("nom: [") is None
    assert read_source('nom: "s"\nlibelle: "S"\nstorage: "st"\ninconnu: 1\n') is None
    # `entrees` qui n'est pas une liste : on ne devine pas ce qu'elle voulait dire.
    assert read_source('nom: "s"\nlibelle: "S"\nstorage: "st"\nentrees: 3\n') is None
    # Une clef inconnue DANS une entrée est refusée aussi : une faute de frappe sur
    # « modes » passerait sinon pour une entrée qui n'expose aucune méthode.
    assert (
        read_source(
            'nom: "s"\nlibelle: "S"\nstorage: "st"\n'
            'entrees:\n  - type: "web"\n    modele_source: "d/m"\n    chaine: "c"\n'
            "    mode: {}\n"
        )
        is None
    )


def test_une_source_sans_entree_est_une_declaration_valide() -> None:
    """Elle dit déjà OÙ ça va, ce qui suffit à l'enregistrer : les entrées viennent après."""
    doc = read_source('nom: "s"\nlibelle: "S"\nstorage: "st"\n')

    assert doc is not None
    assert doc.entries == ()


def test_les_noms_viennent_des_fichiers_du_repertoire_et_sont_ordonnes() -> None:
    paths = ["sources/b.yaml", "storages/a.yaml", "sources/a.yaml", "sources/x/y.yaml"]

    assert names_in(paths) == ["a", "b"]
    assert source_path("a") == "sources/a.yaml"
