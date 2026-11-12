"""La copie du socle EST la racine d'urban-workflow, et c'est ce test qui le tient.

Décision de Gael du 12/11/2026 : tous les events portent « une racine technique d'event qui
est la même et qui est basée sur le package urban-workflow », et cette racine est
« surchargée par un objet racine commun » qui porte ce que Miles ajoute. Le socle déclare
donc les deux : `ENGINE_ROOT_SCHEMA`, qui est la copie de l'amont, et `ROOT_SCHEMA`, qui est
la racine de Miles.

Le socle **recopie** l'amont plutôt que de l'importer, parce qu'`urban-workflow` dépend
d'`urban-json` sans extra et tire le runtime ANTLR : l'importer depuis le socle imposerait
un moteur de transformation au module d'enrôlement, qui n'en installe aucun.

Le portail est le seul produit qui a le moteur installé, donc le seul qui puisse comparer.
**Ce test est ce qui rend la copie tenable** : une montée d'urban-workflow qui ajoute,
retire ou retype un champ de la racine rougit ici, et non six mois plus tard sur un event
qu'un schéma métier refuse sans qu'on sache pourquoi.
"""

from __future__ import annotations

from miles_socle.events.root import (
    COLUMN_OF_FIELD,
    ENGINE_ROOT_FIELDS,
    ENGINE_ROOT_SCHEMA,
    MILES_FIELDS,
    ROOT_SCHEMA,
)
from urban_workflow.schemas import BASE_EVENT_SCHEMA


def test_les_champs_de_la_copie_sont_exactement_ceux_du_moteur() -> None:
    # Les ensembles d'abord : le message d'échec nomme alors le champ ajouté ou retiré par
    # l'amont, ce qu'une égalité de dictionnaires entiers ne dirait pas.
    assert ENGINE_ROOT_FIELDS == set(BASE_EVENT_SCHEMA["properties"])


def test_chaque_champ_est_declare_comme_le_moteur_le_declare() -> None:
    for nom, declaration in BASE_EVENT_SCHEMA["properties"].items():
        assert ENGINE_ROOT_SCHEMA["properties"][nom] == declaration, f"champ {nom}"
    # Puis le tout, qui attrape le reste : $schema, title, type, et la liste des requis.
    assert ENGINE_ROOT_SCHEMA == BASE_EVENT_SCHEMA


def test_la_racine_de_miles_est_celle_du_moteur_plus_ses_propres_champs() -> None:
    """La surcharge AJOUTE : aucun champ du moteur n'y est redéclaré autrement."""
    for nom, declaration in BASE_EVENT_SCHEMA["properties"].items():
        assert ROOT_SCHEMA["properties"][nom] == declaration, f"champ {nom}"
    assert set(ROOT_SCHEMA["properties"]) == set(BASE_EVENT_SCHEMA["properties"]) | set(
        MILES_FIELDS
    )


def test_un_champ_que_le_moteur_se_mettrait_a_porter_ne_passe_pas_inapercu() -> None:
    """La garde qui compte le jour d'une montée de version : si l'amont déclarait à son tour
    une propriété que Miles ajoute, la surcharge l'écraserait en silence et l'event ne
    validerait plus sur ce que le moteur valide."""
    assert set(MILES_FIELDS) & set(BASE_EVENT_SCHEMA["properties"]) == set()


def test_chaque_champ_du_moteur_nomme_la_colonne_qui_le_porte() -> None:
    """Un champ de la racine sans colonne finirait dans le bloc de propriétés, redéclaré
    par chaque type d'event — exactement ce que la racine commune évite. `Category` en est
    l'exception assumée : son énumération n'est pas close."""
    assert set(COLUMN_OF_FIELD) == set(BASE_EVENT_SCHEMA["properties"])
