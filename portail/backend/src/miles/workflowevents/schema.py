"""Le schéma d'un événement : un modèle de données, plus ce que le moteur impose.

Le contrôle du JSON Schema lui-même est celui des modèles (`datamodels.schema`), sans une
ligne de plus : c'est le même dialecte, le même méta-schéma, les mêmes renvois admis. Ce
module n'ajoute que les deux règles qui viennent du MOTEUR, et il les tient de lui plutôt
que d'une recopie.
"""

from __future__ import annotations

import copy
from typing import Any

import yaml
from miles_socle.events.root import ROOT_SCHEMA

from miles.datamodels.grammar import ModelGrammarError, Problem, load_yaml
from miles.datamodels.schema import DIALECT, ModelSchema, parse_schema
from miles.workflowevents.layout import event_id


# LU de la racine commune du socle (`miles_socle.events.root.ROOT_SCHEMA`), qui est celle
# du moteur SURCHARGÉE de ce que Miles ajoute — `Category` depuis le 12/11/2026 (Gael :
# « l'event qui utilise un objet racine fourni par urban-workflow doit être surchargé par
# un objet racine commun qui portera la catégorie »).
#
# Lu de là et non d'`urban_workflow` directement, alors que le portail a le moteur
# installé : la racine de Miles est ce dont dérive un événement, et la prendre du moteur
# ferait accepter ici un champ métier nommé `Category` que le reste du système réserve. La
# fidélité à l'amont reste tenue, à un seul endroit : `tests/test_racine_des_events.py`
# compare la copie du socle au `BASE_EVENT_SCHEMA` du moteur installé.
class EventGrammarError(ModelGrammarError):
    """Un événement non conforme, et c'est une SOUS-CLASSE, non un alias.

    Le dépôt a écrit ailleurs qu'une sous-classe est un piège (`ModelSyntaxError` est un
    alias, pas une sous-classe, pour que l'erreur du socle ne traverse pas tous les
    `except` du produit). Ici le raisonnement s'inverse, et c'est délibéré : tout endroit
    qui attrape `ModelGrammarError` DOIT continuer à attraper celle-ci — la validation de
    branche en rend les manquements, l'écran les affiche de la même façon. Ce que la
    sous-classe apporte, c'est le NOM du refus : le même défaut ne doit pas s'appeler
    `modele_non_conforme` par MCP et `evenement_non_conforme` par la route de l'écran.
    """


_SOCLE: dict[str, Any] = dict(ROOT_SCHEMA.get("properties") or {})
SOCLE_NAMES = frozenset(_SOCLE)


def socle_schema() -> dict[str, Any]:
    """Le socle commun, tel que Miles le porte : un JSON Schema, pas une liste.

    Servi comme SCHÉMA et non comme un tableau de noms, et c'est ce que fait aussi la vue
    « Événements » du playground d'urban-workflow (`api/base-event-schema`) : l'écran peut
    alors le monter dans le MÊME éditeur visuel que les champs métier, verrouillé — ce qui
    montre que l'événement DÉRIVE de ce type, là où un tableau à part se lisait comme une
    annexe. Un aplatissement aurait en outre perdu ce que le schéma dit en plus : les
    `format`, les descriptions, et quelle propriété est obligatoire.

    Copie profonde : le dictionnaire du socle est un singleton de module, et un appelant
    qui le modifierait changerait ce que validera l'événement suivant.
    """
    return copy.deepcopy(ROOT_SCHEMA)


def parse_event_schema(text: str) -> ModelSchema:
    """Lit et vérifie le schéma d'un événement ; lève ModelSyntaxError ou ModelGrammarError.

    Les deux manquements propres aux événements sont MESURÉS sur le moteur, le 11/11/2026 :

    - un schéma **fermé** (`additionalProperties: false`) fait refuser TOUS les payloads
      réels, parce que le moteur valide le socle commun EN PLUS du schéma métier et que
      ses propriétés deviennent alors « inattendues ». Mesure : un schéma fermé déclarant
      `Montant` refuse `{'Name': 'Ping', 'ExternalId': 'X-1', 'Montant': 12}` avec
      « Additional properties are not allowed ('ExternalId', 'Name' were unexpected) ».
      Laisser écrire ça, c'est livrer un événement qu'aucun émetteur ne pourra satisfaire ;
    - une propriété du socle **redéclarée** entre en concurrence avec celle du moteur :
      les deux schémas s'appliquent, et deux types incompatibles rendent le payload
      insatisfiable sans qu'aucun des deux documents paraisse faux.
    """
    schema = parse_schema(text)
    data = load_yaml(text)
    problems = []
    if isinstance(data, dict) and data.get("additionalProperties") is False:
        problems.append(Problem("additionalProperties", "schema_ferme"))
    problems += [
        Problem(f"properties.{nom}", "propriete_du_socle", nom)
        for nom in schema.properties
        if nom in SOCLE_NAMES
    ]
    if problems:
        raise EventGrammarError(problems)
    return schema


def normalized(text: str, scope: str, name: str) -> str:
    """Le schéma tel que Miles l'enregistre : `$schema` et `$id` posés par le système.

    Même geste que pour un modèle — réécriture complète, clés de tête d'abord, les
    commentaires du YAML ne survivent pas —, mais avec l'`$id` d'un événement, qui n'est
    pas celui d'un modèle : c'est lui qui met l'événement hors de portée des storages.
    """
    data = load_yaml(text)
    if not isinstance(data, dict):
        raise EventGrammarError([Problem("", "document_non_objet")])
    head = {"$schema": DIALECT, "$id": event_id(scope, name)}
    rest = {k: v for k, v in data.items() if k not in head}
    return yaml.safe_dump(head | rest, allow_unicode=True, sort_keys=False)


def draft(scope: str, name: str, title: str) -> str:
    """Le schéma d'un événement tout juste déclaré : un objet sans propriété métier."""
    body = {"title": title, "type": "object", "properties": {}}
    return normalized(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), scope, name)
