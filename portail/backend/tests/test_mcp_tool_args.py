"""Ce que les primitives MCP rendent d'un modèle : l'unique seam TYPÉ de leur sortie.

Ce fichier naît d'un défaut réel et de son coût. `Caller.services` est `Any` — il porte
l'`app.state`, dont les attributs ne sont pas déclarés — donc mypy ne voit RIEN de ce
qu'un outil MCP fait d'un service. Le 16/11/2026, `resolve_list` des modèles est passé
d'une liste à un objet `Listing` ; `list_schemas` a continué de l'itérer. Style, types et
936 tests unitaires sont restés verts, et c'est la campagne d'intégration qui l'a dit
— 65 minutes plus tard, sur `UnexpectedToolError: Error executing tool list_schemas`.

Ces tests-ci mettent une seconde. Ils ne remplacent pas le typage de `services`, qui reste
le trou : ils bornent la sortie que ce trou laissait passer.
"""

from __future__ import annotations

from miles.datamodels.layout import ModelEntry
from miles.datamodels.usages import STORAGE, Designation, Listed, Listing
from miles.mcp_api.tool_args import entry_out, listed_out

COLIS = ModelEntry("shared", "colis", "shared/models/colis.yaml", "Colis", 2)
SITE = ModelEntry("suivi", "site", "domains/suivi/models/site.yaml", "Site", 1)
STOCKE = Designation(STORAGE, "sites", "Sites", "storages/sites.yaml", ("shared", "colis"))


def test_la_liste_rendue_a_l_agent_porte_l_emplacement_de_chaque_modele() -> None:
    # Discriminant : deux modèles d'emplacements différents, et le premier désigné par un
    # storage. Un seul modèle sans usage aurait laissé passer à peu près n'importe quoi.
    listing = Listing((Listed(COLIS, (STOCKE,)), Listed(SITE, ())), ())

    assert listed_out(listing) == [
        {"scope": "shared", "name": "colis", "path": "shared/models/colis.yaml"},
        {"scope": "suivi", "name": "site", "path": "domains/suivi/models/site.yaml"},
    ]


def test_les_usages_ne_partent_pas_vers_l_agent() -> None:
    """Un agent qui lit un modèle pour l'écrire n'en a que faire, et `read_listing` les
    fait payer à l'écran qui les montre. Ils entreront le jour où une primitive les
    demandera — pas par habitude de tout rendre."""
    rendu = listed_out(Listing((Listed(COLIS, (STOCKE,)),), ()))

    assert set(rendu[0]) == {"scope", "name", "path"}


def test_une_liste_vide_rend_une_liste_vide_et_non_un_refus() -> None:
    # Le cas « rien trouvé », celui qu'on oublie : une branche neuve n'a aucun modèle, et
    # ce n'est pas une erreur.
    assert listed_out(Listing((), ())) == []


def test_un_modele_seul_se_rend_par_le_meme_gabarit_que_la_liste() -> None:
    # `get_schema` et `create_schema` passent par `entry_out` : les deux sorties ne doivent
    # pas pouvoir diverger d'un champ.
    assert entry_out(COLIS) == listed_out(Listing((Listed(COLIS, ()),), ()))[0]
