from __future__ import annotations

import pytest

from environnement.sources.declarations import file_declared_sources

COMPTES = """
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
"""
SITES = """
nom: "sites-pudo"
libelle: "Sites PUDO"
storage: "sites"
entrees: []
"""


def _arbre(fichiers: dict[str, str]):
    async def read(path: str) -> str | None:
        return fichiers.get(path)

    return read


@pytest.mark.asyncio
async def test_les_sources_lisibles_sont_rendues_avec_leur_declaration() -> None:
    declared = await file_declared_sources(
        _arbre({"sources/comptes-pudo.yaml": COMPTES, "sources/sites-pudo.yaml": SITES}),
        ["sources/comptes-pudo.yaml", "sources/sites-pudo.yaml", "storages/accounts.yaml"],
    )

    assert set(declared.readable) == {"comptes-pudo", "sites-pudo"}
    assert declared.unreadable == ()
    assert declared.names == ("comptes-pudo", "sites-pudo")
    assert declared.readable["comptes-pudo"].storage == "accounts"
    assert declared.readable["comptes-pudo"].entries[0].modes.batch is True


@pytest.mark.asyncio
async def test_un_arbre_sans_source_ne_declare_rien() -> None:
    """Et ce n'est pas une erreur : une version peut ne rien recevoir en entrée."""
    declared = await file_declared_sources(_arbre({}), ["storages/accounts.yaml"])

    assert declared.readable == {} and declared.unreadable == ()
    assert declared.names == ()


@pytest.mark.asyncio
async def test_une_declaration_illisible_est_nommee_et_non_ecartee() -> None:
    """L'écarter ferait chercher une source absente alors qu'elle est là, et fautive."""
    declared = await file_declared_sources(
        _arbre({"sources/cassee.yaml": "nom: [", "sources/sites-pudo.yaml": SITES}),
        ["sources/cassee.yaml", "sources/sites-pudo.yaml"],
    )

    assert declared.unreadable == ("cassee",)
    assert set(declared.readable) == {"sites-pudo"}
    # Elle reste DÉCLARÉE : un octroi qui la désigne n'est pas un octroi vers l'inconnu.
    assert declared.names == ("cassee", "sites-pudo")


@pytest.mark.asyncio
async def test_un_nom_qui_contredit_le_fichier_rend_la_source_illisible() -> None:
    """Deux noms pour un même objet : une adresse d'ingestion et un octroi ne
    désigneraient pas la même source."""
    declared = await file_declared_sources(
        _arbre({"sources/sites-pudo.yaml": COMPTES}), ["sources/sites-pudo.yaml"]
    )

    assert declared.readable == {}
    assert declared.unreadable == ("sites-pudo",)


@pytest.mark.asyncio
async def test_un_fichier_manquant_a_l_index_ne_fait_pas_tomber_la_lecture() -> None:
    """`ls-files` liste l'index ; un fichier absent du disque se signale, il ne lève pas."""
    declared = await file_declared_sources(_arbre({}), ["sources/fantome.yaml"])

    assert declared.unreadable == ("fantome",)
