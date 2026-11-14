"""Ce que le MOTEUR exige d'un modèle désigné par un `DEFINE EVENT`.

Un type d'event ne décrit plus son payload avec un document à lui : il DÉSIGNE un modèle
de données (`AS @shared.colis`). Le modèle, lui, se valide comme tous les autres —
`datamodels.schema`, même dialecte, même méta-schéma. Ce module ne porte que les règles
qui viennent du moteur, et elles s'appliquent à la DÉCLARATION, pas au fichier : un
modèle n'a aucune raison de les respecter tant que rien ne le déclare comme type d'event.

C'est le renversement du 13/11/2026 : ce qui fait d'un modèle un type d'event est qu'un
`DEFINE EVENT` le nomme. Un modèle rangé sous `models/` sert indifféremment un storage,
une source ou un type d'event — et ne porte la contrainte du moteur que dans ce dernier
cas.
"""

from __future__ import annotations

import copy
from typing import Any

from miles_socle.events.root import ROOT_SCHEMA

from miles.datamodels.grammar import ModelGrammarError, Problem, load_yaml
from miles.datamodels.schema import ModelSchema
from miles.workflowevents.dsl import writable

# LU de la racine commune du socle (`miles_socle.events.root.ROOT_SCHEMA`), qui est celle
# du moteur SURCHARGÉE de ce que Miles ajoute — `Category` depuis le 12/11/2026 (Gael :
# « l'event qui utilise un objet racine fourni par urban-workflow doit être surchargé par
# un objet racine commun qui portera la catégorie »).
#
# Lu de là et non d'`urban_workflow` directement, alors que le portail a le moteur
# installé : la racine de Miles est ce dont dérive un event, et la prendre du moteur
# ferait accepter ici un champ métier nommé `Category` que le reste du système réserve. La
# fidélité à l'amont reste tenue, à un seul endroit : `tests/test_racine_des_events.py`
# compare la copie du socle au `BASE_EVENT_SCHEMA` du moteur installé.
_SOCLE: dict[str, Any] = dict(ROOT_SCHEMA.get("properties") or {})
SOCLE_NAMES = frozenset(_SOCLE)


class EventModelError(ModelGrammarError):
    """Le modèle désigné ne peut pas porter un event, et c'est une SOUS-CLASSE.

    Le dépôt a écrit ailleurs qu'une sous-classe est un piège (`ModelSyntaxError` est un
    alias, pas une sous-classe, pour que l'erreur du socle ne traverse pas tous les
    `except` du produit). Ici le raisonnement s'inverse, et c'est délibéré : tout endroit
    qui attrape `ModelGrammarError` DOIT continuer à attraper celle-ci — la validation de
    branche en rend les manquements, l'écran les affiche de la même façon. Ce que la
    sous-classe apporte, c'est le NOM du refus.
    """


def socle_schema() -> dict[str, Any]:
    """Le socle commun, tel que Miles le porte : un JSON Schema, pas une liste.

    Servi comme SCHÉMA et non comme un tableau de noms, et c'est ce que fait aussi la vue
    « Événements » du playground d'urban-workflow (`api/base-event-schema`) : l'écran peut
    alors le monter dans le MÊME éditeur visuel que les champs métier, verrouillé — ce qui
    montre qu'un event DÉRIVE de ce type, là où un tableau à part se lisait comme une
    annexe. Un aplatissement aurait en outre perdu ce que le schéma dit en plus : les
    `format`, les descriptions, et quelle propriété est obligatoire.

    Copie profonde : le dictionnaire du socle est un singleton de module, et un appelant
    qui le modifierait changerait ce que validera la déclaration suivante.
    """
    return copy.deepcopy(ROOT_SCHEMA)


def payload_problems(text: str, schema: ModelSchema) -> list[Problem]:
    """Ce qui empêche un modèle de servir de payload d'event. Vide : il peut.

    Les deux manquements sont MESURÉS sur le moteur, le 11/11/2026 :

    - un schéma **fermé** (`additionalProperties: false`) fait refuser TOUS les payloads
      réels, parce que le moteur valide le socle commun EN PLUS du schéma métier et que
      ses propriétés deviennent alors « inattendues ». Mesure : un schéma fermé déclarant
      `Montant` refuse `{'Name': 'Ping', 'ExternalId': 'X-1', 'Montant': 12}` avec
      « Additional properties are not allowed ('ExternalId', 'Name' were unexpected) ».
      Déclarer un tel modèle, c'est livrer un type d'event qu'aucun émetteur ne satisfera ;
    - une propriété du socle **redéclarée** entre en concurrence avec celle du moteur :
      les deux schémas s'appliquent, et deux types incompatibles rendent le payload
      insatisfiable sans qu'aucun des deux documents paraisse faux.

    Un modèle VIDE, en revanche, est ici légitime : un `DEFINE EVENT` peut n'apporter que
    le socle commun — un nom, un `ExternalId`, une date — et déclencher une transition sur
    ce seul fait. (Une version de la branche refuse un modèle vide pour une autre raison,
    qui lui est propre : il ne décrit rien qu'un terminal puisse recevoir.)
    """
    data = load_yaml(text)
    problems = []
    if isinstance(data, dict) and data.get("additionalProperties") is False:
        problems.append(Problem("additionalProperties", "schema_ferme"))
    problems += [
        Problem(f"properties.{nom}", "propriete_du_socle", nom)
        for nom in schema.properties
        if nom in SOCLE_NAMES
    ]
    return problems


def dedup_problems(keys: tuple[str, ...], schema: ModelSchema) -> list[Problem]:
    """Ce qui empêche des clés d'unicité de servir. Vide : elles servent.

    Une clé désigne une propriété du PAYLOAD, donc du modèle métier ou du socle commun :
    `UNIQUE (ExternalId)` est le cas le plus courant, et il ne vient pas du modèle. Une
    clé qui ne désigne rien donnerait un hash d'anti-doublon calculé sur du vide pour tous
    les events — `compute_dedup_hash` compte une propriété absente comme vide —, donc un
    référentiel où deux events différents se dédoublonneraient l'un l'autre.
    """
    known = set(schema.properties) | SOCLE_NAMES
    problems = []
    for index, key in enumerate(keys):
        if not writable(key):
            # Refusé AVANT d'écrire : `UNIQUE (Mon-Champ)` ne se relit pas, et un artefact
            # illisible fait échouer le chargement de tout le répertoire du moteur.
            problems.append(Problem(f"unique.{index}", "cle_non_ecrivable", key))
        elif key not in known:
            # Un code À ELLE, et non `propriete_inconnue` ni `cle_inconnue` : les deux
            # existent déjà ailleurs, avec des libellés qui parlent du modèle d'un
            # storage et d'une clé de traduction. Deux refus différents sous le même code
            # afficheraient la mauvaise phrase à l'un des deux.
            problems.append(Problem(f"unique.{index}", "cle_d_unicite_inconnue", key))
    return problems
