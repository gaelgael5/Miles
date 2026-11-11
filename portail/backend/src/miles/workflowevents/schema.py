"""Le schéma d'un événement : un modèle de données, plus ce que le moteur impose.

Le contrôle du JSON Schema lui-même est celui des modèles (`datamodels.schema`), sans une
ligne de plus : c'est le même dialecte, le même méta-schéma, les mêmes renvois admis. Ce
module n'ajoute que les deux règles qui viennent du MOTEUR, et il les tient de lui plutôt
que d'une recopie.
"""

from __future__ import annotations

from typing import Any

import yaml
from urban_workflow.schemas import BASE_EVENT_SCHEMA

from miles.datamodels.grammar import ModelGrammarError, Problem, load_yaml
from miles.datamodels.schema import DIALECT, ModelSchema, parse_schema
from miles.workflowevents.layout import event_id


# LU du moteur installé, jamais recopié (`urban_workflow.schemas.BASE_EVENT_SCHEMA`) : le
# socle commun de tout événement — `Name`, `Uuid`, `ExternalId`, `CreationDate`,
# `EventDate`, `DedupKey`, et `IntegrationDate` que le moteur pose lui-même à
# l'intégration. Une recopie aurait divergé à la première montée de version sans que rien
# ne le signale, et c'est précisément ce que le portail doit éviter : il refuse à
# l'écriture ce que le moteur refuserait à l'exécution, donc il doit refuser d'après LUI.
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


_SOCLE: dict[str, Any] = dict(BASE_EVENT_SCHEMA.get("properties") or {})
SOCLE_NAMES = frozenset(_SOCLE)


def socle_fields() -> list[tuple[str, str, bool]]:
    """(nom, type, posé par le moteur) de chaque propriété du socle, pour l'écran.

    Les montrer est le seul moyen qu'a la personne de savoir sur quoi elle peut compter
    dans un payload — et de ne pas les redéclarer, ce que la grammaire refuse ci-dessous.
    """
    champs = []
    for nom, forme in _SOCLE.items():
        type_declare = forme.get("type") if isinstance(forme, dict) else None
        lecture_seule = bool(forme.get("readOnly")) if isinstance(forme, dict) else False
        champs.append((nom, str(type_declare or "?"), lecture_seule))
    return champs


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
