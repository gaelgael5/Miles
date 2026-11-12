"""La racine des events du socle EST celle d'urban-workflow, et c'est ce test qui le tient.

Décision de Gael du 12/11/2026 : tous les events portent « une racine technique d'event qui
est la même et qui est basée sur le package urban-workflow ». Le socle la **recopie**
(`miles_socle.events.root`) plutôt que d'importer le moteur, parce qu'`urban-workflow`
dépend d'`urban-json` sans extra et tire le runtime ANTLR : l'importer depuis le socle
imposerait un moteur de transformation au module d'enrôlement, qui n'en installe aucun.

Le portail est le seul produit qui a le moteur installé, donc le seul qui puisse comparer.
**Ce test est ce qui rend la copie tenable** : une montée d'urban-workflow qui ajoute,
retire ou retype un champ de la racine rougit ici, et non six mois plus tard sur un event
qu'un schéma métier refuse sans qu'on sache pourquoi.
"""

from __future__ import annotations

from miles_socle.events.root import COLUMN_OF_FIELD, ROOT_FIELDS, ROOT_SCHEMA
from urban_workflow.schemas import BASE_EVENT_SCHEMA


def test_les_champs_de_la_racine_sont_exactement_ceux_du_moteur() -> None:
    # Les ensembles d'abord : le message d'échec nomme alors le champ ajouté ou retiré par
    # l'amont, ce qu'une égalité de dictionnaires entiers ne dirait pas.
    assert ROOT_FIELDS == set(BASE_EVENT_SCHEMA["properties"])


def test_chaque_champ_est_declare_comme_le_moteur_le_declare() -> None:
    for nom, declaration in BASE_EVENT_SCHEMA["properties"].items():
        assert ROOT_SCHEMA["properties"][nom] == declaration, f"champ {nom}"
    # Puis le tout, qui attrape le reste : $schema, title, type, et la liste des requis.
    assert ROOT_SCHEMA == BASE_EVENT_SCHEMA


def test_chaque_champ_de_la_racine_nomme_la_colonne_qui_le_porte() -> None:
    """Un champ de la racine sans colonne finirait dans le bloc de propriétés, redéclaré
    par chaque type d'event — exactement ce que la racine commune évite."""
    assert set(COLUMN_OF_FIELD) == ROOT_FIELDS
