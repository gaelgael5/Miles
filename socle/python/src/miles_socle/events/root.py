"""La racine technique commune à TOUS les events, quelle que soit leur catégorie.

Décision de Gael du 12/11/2026 : « tous les events dans l'application tombent dans la même
table d'évènement […] avec une racine technique d'event qui est la même et qui est basée
sur le package urban-workflow ». Puis, le même jour : « l'event qui utilise un objet racine
fourni par urban-workflow doit être surchargé par un objet racine commun qui portera la
catégorie et d'autre futures propriétés si ça arrive. »

Il y a donc **deux racines, et c'est voulu** :

- `ENGINE_ROOT_SCHEMA` — celle du moteur, telle qu'il la porte. Elle ne nous appartient
  pas : on la suit.
- `ROOT_SCHEMA` — **celle de Miles**, qui est la première PLUS ce que Miles ajoute
  (`MILES_FIELDS`). C'est d'elle que dérive tout schéma d'event, et c'est elle que l'écran
  montre verrouillée au-dessus des champs métier.

Ce découpage est ce qui permet d'ajouter une propriété à nous sans toucher à la copie de
l'amont, et de voir en un coup d'œil ce qui vient de qui — « d'autres futures propriétés si
ça arrive » devient une ligne dans `MILES_FIELDS`, pas une divergence silencieuse.

**Pourquoi la racine du moteur est RECOPIÉE ici plutôt qu'importée.** Mesuré le
12/11/2026 : `urban-workflow` dépend d'`urban-json` sans extra, et tire le runtime ANTLR.
L'importer depuis le socle imposerait le moteur de transformation au module d'enrôlement,
qui n'en installe aucun — invariant du dépôt, tenu par `tests/`. La divergence que toute
copie finit par produire est tenue par une garde DU PORTAIL, seul produit qui a le moteur
installé : `tests/test_racine_des_events.py` compare champ par champ et rougit sur un champ
ajouté, retiré ou dont le format a changé. Une copie éprouvée, pas une copie laissée vivre.

**Où vivent ces champs** : dans les COLONNES du journal, nommées par `COLUMN_OF_FIELD`, et
jamais dans le bloc de propriétés. Un champ de la racine rangé dans le bloc serait
redéclaré par chaque type d'event, et deux producteurs finiraient par le nommer
différemment — ce que le catalogue de types ne pourrait plus rattraper.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

from miles_socle.events.categories import CATEGORIES

ENGINE_ROOT_SCHEMA: Final[dict[str, Any]] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "urban-workflow base event",
    "type": "object",
    "properties": {
        "Name": {"type": "string", "minLength": 1},
        "Uuid": {"type": "string", "format": "uuid"},
        "ExternalId": {"type": "string"},
        "CreationDate": {"type": "string", "format": "date-time"},
        "EventDate": {"type": "string", "format": "date-time"},
        "DedupKey": {"type": "string", "minLength": 1},
        "IntegrationDate": {
            "type": "string",
            "format": "date-time",
            "readOnly": True,
            "description": "Date d'insertion de l'événement dans le système (posée par le moteur).",
        },
    },
    "required": ["Name"],
}

# Ce que Miles ajoute à la racine du moteur, et rien d'autre. Toute propriété posée ici est
# verrouillée pour les schémas métier, exactement comme celles du moteur.
#
# `Category` dit QUI INTRODUIT l'event (Gael, 12/11/2026), et c'est de là que l'IHM de
# configuration tire le droit de l'éditer ou non : un type introduit par du code y est en
# lecture seule.
#
# **Un ENTIER, et son énumération est celle des catégories déclarées.** « On reste sur les
# numéros » (Gael, 12/11/2026) : c'est le numéro qui voyage sur le fil et dans le contrat
# publié, donc le porter en chaîne ici aurait donné deux formes pour la même valeur — un
# écran la lirait `5`, un contrat `"device-fonctionnel"`, et la conversion se serait
# installée quelque part au milieu.
#
# L'énumération est DÉRIVÉE de `CATEGORIES`, jamais recopiée : une septième catégorie
# ajoutée là-bas entre ici toute seule. Une liste écrite à la main aurait laissé passer un
# ajout, et le schéma aurait refusé une valeur que le code accepte.
MILES_FIELDS: Final[Mapping[str, Any]] = {
    "Category": {
        "type": "integer",
        "enum": [item.number for item in CATEGORIES],
        "description": "Qui introduit l'event ; un type introduit par du code est en "
        "lecture seule dans l'IHM de configuration.",
    },
}


def _miles_root() -> dict[str, Any]:
    """La racine du moteur, surchargée de ce que Miles ajoute.

    Assemblée et non recopiée à la main : une recopie aurait figé les sept champs du moteur
    une seconde fois, et la garde du portail n'en aurait surveillé qu'une.
    """
    racine = copy.deepcopy(ENGINE_ROOT_SCHEMA)
    racine["title"] = "racine commune des events de Miles"
    racine["properties"].update(copy.deepcopy(dict(MILES_FIELDS)))
    return racine


ROOT_SCHEMA: Final[dict[str, Any]] = _miles_root()

# La correspondance champ de la racine ↔ colonne du journal, écrite UNE fois. Les quatre
# premières existaient avant la décision du 12/11/2026 sous d'autres noms : le journal
# portait déjà la racine du moteur sans le dire. Les trois suivantes sont ce que cette
# racine apporte — et `ExternalId` répond exactement à une décision de l'epic qui n'avait
# pas de support : « quand la modification vient d'un message reçu, l'event consigne
# l'identifiant de ce message, stable à travers les ré-émissions ».
#
# `Category` n'y est PAS, et c'est délibéré : son énumération n'est pas close, donc aucun
# producteur ne peut poser une valeur juste aujourd'hui. Une colonne qu'on ne sait pas
# remplir se remplirait de la première valeur plausible. Elle viendra avec le catalogue de
# types, qui est l'endroit où la catégorie est déclarée.
#
# `DedupKey` a sa colonne mais AUCUN producteur, et c'est délibéré aussi. Une colonne que
# personne n'écrit ressemble sinon à un oubli, et le prochain lecteur la câblerait sur ce
# qu'il a sous la main : le candidat le plus proche serait justement le pire — le nonce de
# l'enveloppe d'appel est NEUF à chaque envoi, donc deux émissions du même message auraient
# deux clés et se dédoubleraient toutes les deux.
#
# D'OÙ ELLE VIENDRA, mesuré le 12/11/2026 sur urban-workflow 0.2.1 : du paramétrage du
# workflow, et de nulle part ailleurs. `DEFINE EVENT X 'l' AS @schema UNIQUE (A, B);`
# déclare les propriétés qui font le doublon, et `urban_workflow.schemas.compute_dedup_hash`
# en fait un SHA-256 — **sensible à l'ordre** des clefs déclarées, et rendant le hash de la
# chaîne vide quand la liste est vide. C'est donc l'ÉVALUATION, au module d'environnement,
# qui la posera (Gael, 12/11/2026), et jamais un producteur du back-office.
COLUMN_OF_FIELD: Final[Mapping[str, str]] = {
    "Name": "type",
    "Uuid": "id",
    "EventDate": "functional_at",
    "IntegrationDate": "written_at",
    "ExternalId": "external_id",
    "CreationDate": "creation_date",
    "DedupKey": "dedup_key",
    # Depuis le 12/11/2026, et c'est le dernier champ de la racine à en recevoir une : la
    # colonne n'a pu être posée NOT NULL que le jour où les TROIS produits ont déclaré la
    # catégorie de chacun de leurs types. Avant, rien ne savait poser une valeur juste, et
    # une colonne nullable aurait laissé l'IHM de configuration sans son verrou.
    "Category": "category",
}

ENGINE_ROOT_FIELDS: Final[frozenset[str]] = frozenset(ENGINE_ROOT_SCHEMA["properties"])
#: Tout ce qu'un schéma métier ne peut pas redéclarer : la racine du moteur ET nos ajouts.
ROOT_FIELDS: Final[frozenset[str]] = frozenset(ROOT_SCHEMA["properties"])

# Ce que Miles ajoute autour de la racine, en colonnes, et qui n'entre pas dans le schéma
# d'un event : l'auteur `(annuaire, sub)`, les objets concernés et leur numéro de séquence,
# et la provenance de la date fonctionnelle. Nommé ici pour que la lecture de
# `COLUMN_OF_FIELD` ne laisse pas croire que les autres colonnes du journal sont un oubli.
OUTSIDE_ROOT: Final[tuple[str, ...]] = (
    "author_directory",
    "author_subject",
    # Le CURSEUR du journal (12/11/2026). Hors racine délibérément : il n'identifie pas
    # l'event — `Uuid` le fait — et il n'a pas de sens hors de LA base qui l'a attribué.
    # Deux journaux de deux produits ont chacun leur séquence, et les mélanger n'aurait
    # aucun sens. Un consommateur le garde comme repère de progression, rien de plus.
    "cursor_seq",
    "functional_at_source",
    "object_kind",
    "object_id",
    "sequence",
)


class EventNotion(StrEnum):
    """Les notions d'event que Gael distingue (12/11/2026), dans ses mots.

    Elles ne changent ni la racine ni la table : elles disent **de quoi un type d'event
    parle**, ce qu'aucun nom de type ne dit de façon fiable.

    **Leur rapport avec `Category` est une question ouverte** : la notion dit de quoi
    l'event parle, la catégorie dit qui l'introduit. Rien ne s'appuie encore sur cette
    énumération ; si l'arbitrage les fusionne, c'est elle qui disparaît.
    """

    # « des évènements techniques du backoffice permettant de traiter des sujets
    # backoffice » : tout ce que trace l'atelier aujourd'hui.
    BACKOFFICE = "backoffice_technique"
    # « des evènements techniques permettant aux socles des devices de fonctionner ».
    DEVICE_SOCLE = "device_technique"
    # « des evènements fonctionnels venant des devices pour appliquer la configuration que
    # nous allons déployer ».
    DEVICE_FONCTIONNEL = "device_fonctionnel"
