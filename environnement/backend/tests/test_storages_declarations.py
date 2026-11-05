from __future__ import annotations

import pytest

from environnement.storages.declarations import file_declared
from environnement.storages.model import (
    REFUSAL_BAD_MODEL,
    REFUSAL_BAD_NAME,
    REFUSAL_COLUMN_CLASH,
    REFUSAL_INDEX_NAME,
    REFUSAL_MODEL_MISSING,
    REFUSAL_NOT_SCALAR,
    REFUSAL_TOO_MANY_COLUMNS,
    REFUSAL_UNKNOWN_PROPERTY,
    REFUSAL_UNREADABLE,
    Projection,
)

# Le modèle réel du workspace de Gael, réduit : `Contact` y est un renvoi interne, et
# c'est le cas qui a fait écrire la marche de schéma — sans suivre le renvoi, aucune des
# deux colonnes qu'il a déclarées n'existerait.
ACCOUNTS = """
$schema: https://json-schema.org/draft/2020-12/schema
$id: miles:/domains/pudo/accounts
title: Accounts
type: object
properties:
  AccountId: {type: string}
  Postes: {type: integer}
  Ouvert: {type: boolean}
  Note: {}
  Contact: {$ref: '#/$defs/Contact'}
  Tournees:
    type: array
    items:
      type: object
      properties:
        Code: {type: string}
$defs:
  Contact:
    type: object
    properties:
      Phone: {type: string}
      Email: {type: string}
"""
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
  - nom: "index-2"
    colonnes:
      - "$.Contact.Email"
"""


def _arbre(**fichiers: str) -> dict[str, str]:
    return {
        "domains/pudo/messages/accounts.yaml": ACCOUNTS,
        "storages/accounts.yaml": DECLARATION,
        **fichiers,
    }


async def _declare(fichiers: dict[str, str]) -> tuple[list[object], list[object]]:
    async def read(path: str) -> str | None:
        return fichiers.get(path)

    declared = await file_declared(read, list(fichiers))
    return declared.tables, declared.refusals


@pytest.mark.asyncio
async def test_le_storage_de_gael_donne_sa_table_ses_colonnes_et_ses_index() -> None:
    tables, refus = await _declare(_arbre())

    assert refus == []
    table = tables[0]
    assert (table.schema, table.table, table.label) == ("pudo", "accounts", "Accounts")
    assert table.keys == ("$.AccountId",)
    assert table.projections == (
        Projection("contact_phone", ("Contact", "Phone"), "string", "text"),
        Projection("contact_email", ("Contact", "Email"), "string", "text"),
    )
    assert [(i.name, i.columns) for i in table.indexes] == [
        ("index-1", ("contact_phone",)),
        ("index-2", ("contact_email",)),
    ]


@pytest.mark.asyncio
async def test_le_type_de_la_colonne_est_celui_que_le_modele_garantit() -> None:
    declaration = DECLARATION.replace('"$.Contact.Phone"', '"$.Postes"').replace(
        '"$.Contact.Email"', '"$.Ouvert"'
    )
    tables, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert refus == []
    assert [(p.column, p.sql_type) for p in tables[0].projections] == [
        ("postes", "bigint"),
        ("ouvert", "boolean"),
    ]


@pytest.mark.asyncio
async def test_une_propriete_sans_type_reste_en_text() -> None:
    """On ne type que ce que le modèle prouve."""
    declaration = DECLARATION.replace('"$.Contact.Phone"', '"$.Note"')
    tables, _ = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert tables[0].projections[0] == Projection("note", ("Note",), "valeur", "text")


@pytest.mark.asyncio
async def test_une_colonne_que_le_modele_n_offre_plus_fait_refuser_le_storage() -> None:
    """Le défaut que Gael a rencontré le 01/11/2026 côté portail, dans l'autre produit.

    Refusé et NOMMÉ, jamais posé en text « au cas où » : une colonne muette aurait rendu
    un filtre qui ne trouve jamais rien, sans que rien ne dise pourquoi.
    """
    declaration = DECLARATION.replace('"$.Contact.Phone"', '"$.PhoneNumber"')
    tables, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert tables == []
    assert [(r.storage, r.code, r.detail) for r in refus] == [
        ("accounts", REFUSAL_UNKNOWN_PROPERTY, "$.PhoneNumber")
    ]


@pytest.mark.asyncio
async def test_une_propriete_atteinte_a_travers_un_tableau_est_refusee() -> None:
    declaration = DECLARATION.replace('"$.Contact.Phone"', '"$.Tournees[0].Code"')
    _, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert [(r.code, r.detail) for r in refus] == [(REFUSAL_NOT_SCALAR, "$.Tournees[0].Code")]


@pytest.mark.asyncio
async def test_un_conteneur_est_refuse_comme_colonne() -> None:
    declaration = DECLARATION.replace('"$.Contact.Phone"', '"$.Contact"')
    _, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert [(r.code, r.detail) for r in refus] == [(REFUSAL_NOT_SCALAR, "$.Contact")]


@pytest.mark.asyncio
async def test_un_modele_absent_de_la_version_fait_refuser_le_storage() -> None:
    fichiers = {"storages/accounts.yaml": DECLARATION}
    tables, refus = await _declare(fichiers)

    assert tables == []
    assert [(r.code, r.detail) for r in refus] == [(REFUSAL_MODEL_MISSING, "pudo/accounts")]


@pytest.mark.asyncio
async def test_une_declaration_illisible_est_refusee_et_nommee() -> None:
    _, refus = await _declare(_arbre(**{"storages/accounts.yaml": "nom: ["}))

    assert [(r.code, r.detail) for r in refus] == [(REFUSAL_UNREADABLE, "storages/accounts.yaml")]


@pytest.mark.asyncio
async def test_un_nom_declare_different_du_fichier_est_refuse() -> None:
    """La table porte le nom du storage : deux noms en désaccord la rendraient indécidable."""
    declaration = DECLARATION.replace('nom: "accounts"', 'nom: "autre"')
    _, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert [(r.code, r.detail) for r in refus] == [(REFUSAL_BAD_NAME, "autre")]


@pytest.mark.asyncio
async def test_un_domaine_qui_ne_fait_pas_un_nom_de_schema_est_refuse() -> None:
    declaration = DECLARATION.replace('"pudo/accounts"', '"PUDO/accounts"')
    _, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert [(r.code,) for r in refus] == [(REFUSAL_BAD_MODEL,)]


@pytest.mark.asyncio
async def test_un_index_de_plus_de_trois_colonnes_est_refuse() -> None:
    declaration = DECLARATION.replace(
        '      - "$.Contact.Phone"',
        '      - "$.Contact.Phone"\n      - "$.Postes"\n      - "$.Ouvert"\n      - "$.Note"',
    )
    _, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert [(r.code, r.detail) for r in refus] == [(REFUSAL_TOO_MANY_COLUMNS, "index-1")]


@pytest.mark.asyncio
async def test_un_nom_d_index_hostile_est_refuse_avant_tout_sql() -> None:
    declaration = DECLARATION.replace('nom: "index-1"', 'nom: "x\\"; drop table t; --"')
    _, refus = await _declare(_arbre(**{"storages/accounts.yaml": declaration}))

    assert [r.code for r in refus] == [REFUSAL_INDEX_NAME]


@pytest.mark.asyncio
async def test_deux_chemins_qui_se_reduisent_au_meme_nom_de_colonne_sont_refuses() -> None:
    """Plutôt qu'un suffixe que personne ne pourrait relier à son chemin."""
    modele = ACCOUNTS.replace("  Note: {}", "  Note: {}\n  contact_phone: {type: string}")
    declaration = DECLARATION.replace('"$.Contact.Email"', '"$.contact_phone"')
    tables, refus = await _declare(
        _arbre(
            **{
                "domains/pudo/messages/accounts.yaml": modele,
                "storages/accounts.yaml": declaration,
            }
        )
    )

    assert tables == []
    assert [(r.code, r.detail) for r in refus] == [(REFUSAL_COLUMN_CLASH, "contact_phone")]


@pytest.mark.asyncio
async def test_un_storage_fautif_n_empeche_pas_les_autres_d_etre_materialises() -> None:
    """Critère 7 : les autres sont tout de même matérialisés, et le refus est consultable."""
    sites = 'nom: "sites"\nlibelle: "Sites"\nmodele: "pudo/site"\ncle: ["$.Id"]\nindex: []\n'
    modele = "type: object\nproperties:\n  Id: {type: string}\n"
    tables, refus = await _declare(
        _arbre(
            **{
                "storages/accounts.yaml": DECLARATION.replace('"$.Contact.Phone"', '"$.Disparu"'),
                "storages/sites.yaml": sites,
                "domains/pudo/messages/site.yaml": modele,
            }
        )
    )

    assert [t.storage for t in tables] == ["sites"]
    assert [r.storage for r in refus] == ["accounts"]


@pytest.mark.asyncio
async def test_un_renvoi_vers_un_autre_modele_est_resolu_comme_le_portail_le_resout() -> None:
    """Sans quoi l'écran proposerait une colonne que l'environnement refuserait."""
    modele = ACCOUNTS.replace(
        "  Contact: {$ref: '#/$defs/Contact'}",
        "  Contact: {$ref: 'miles:/domains/pudo/contact'}",
    )
    contact = "type: object\nproperties:\n  Phone: {type: string}\n  Email: {type: string}\n"
    tables, refus = await _declare(
        _arbre(
            **{
                "domains/pudo/messages/accounts.yaml": modele,
                "domains/pudo/messages/contact.yaml": contact,
            }
        )
    )

    assert refus == []
    assert [p.column for p in tables[0].projections] == ["contact_phone", "contact_email"]


# L'utilité des champs, déclarée sur le MODÈLE (Gael, 05/11/2026) : ce qui identifie un
# objet, et ce que le tableau des objets montre.
UTILITE = """
x-miles:
  key:
    - "$.AccountId"
  columns:
    - "$.AccountId"
    - "$.Postes"
"""


@pytest.mark.asyncio
async def test_le_modele_decide_des_colonnes_du_tableau_et_de_leur_ordre() -> None:
    # Cochées sur la page du modèle, elles doivent se retrouver dans la table SANS être
    # redéclarées sur le storage : c'est ce que « le modèle décide, le storage suit »
    # veut dire, et sans cette lecture la case cochée ne change rien nulle part.
    tables, refus = await _declare(
        _arbre(**{"domains/pudo/messages/accounts.yaml": ACCOUNTS + UTILITE})
    )

    assert refus == []
    assert [p.column for p in tables[0].projections] == [
        "accountid",
        "postes",
        "contact_phone",
        "contact_email",
    ]


@pytest.mark.asyncio
async def test_la_cle_du_modele_l_emporte_sur_celle_du_storage() -> None:
    modele = ACCOUNTS + UTILITE.replace('"$.AccountId"\n  columns', '"$.Postes"\n  columns')
    tables, _ = await _declare(_arbre(**{"domains/pudo/messages/accounts.yaml": modele}))

    assert tables[0].keys == ("$.Postes",)


@pytest.mark.asyncio
async def test_un_storage_dont_le_modele_ne_declare_rien_garde_sa_propre_cle() -> None:
    # Les storages déclarés avant cet écran continuent de fonctionner : sans ce repli,
    # ils perdraient leur clé fonctionnelle le jour de la livraison.
    tables, _ = await _declare(_arbre())

    assert tables[0].keys == ("$.AccountId",)


@pytest.mark.asyncio
async def test_une_colonne_du_modele_que_le_modele_n_offre_pas_fait_refuser_le_storage() -> None:
    # Même règle que pour un index : rien n'est deviné, et une colonne muette serait
    # pire qu'un refus nommé. Le cas arrive quand le YAML est retouché à la main.
    modele = ACCOUNTS + UTILITE.replace('"$.Postes"', '"$.Disparu"')
    _, refus = await _declare(_arbre(**{"domains/pudo/messages/accounts.yaml": modele}))

    assert [(r.storage, r.code, r.detail) for r in refus] == [
        ("accounts", REFUSAL_UNKNOWN_PROPERTY, "$.Disparu")
    ]


@pytest.mark.asyncio
async def test_une_colonne_declaree_des_deux_cotes_n_est_posee_qu_une_fois() -> None:
    modele = ACCOUNTS + UTILITE.replace('"$.Postes"', '"$.Contact.Phone"')
    tables, refus = await _declare(_arbre(**{"domains/pudo/messages/accounts.yaml": modele}))

    assert refus == []
    assert [p.column for p in tables[0].projections] == [
        "accountid",
        "contact_phone",
        "contact_email",
    ]
