"""La racine technique commune à TOUS les events, quelle que soit leur notion.

Décision de Gael du 12/11/2026 : « tous les events dans l'application tombent dans la même
table d'évènement […] avec une racine technique d'event qui est la même et qui est basée
sur le package urban-workflow ». Trois notions s'y distinguent — voir `EventNotion` —, mais
la racine ne varie pas : c'est elle qui fait qu'un event du back-office et un event venu
d'un device se relisent de la même façon.

**Pourquoi la racine est RECOPIÉE ici plutôt qu'importée d'urban-workflow.** Mesuré le
12/11/2026 : `urban-workflow` dépend d'`urban-json` sans extra, et tire le runtime ANTLR.
L'importer depuis le socle imposerait le moteur de transformation au module d'enrôlement,
qui n'en installe aucun — invariant du dépôt, tenu par `tests/`. La divergence que toute
copie finit par produire est tenue par une garde DU PORTAIL, seul produit qui a le moteur
installé : `tests/test_racine_des_events.py` compare cette déclaration à
`BASE_EVENT_SCHEMA` et rougit sur un champ ajouté, retiré ou dont le format a changé. Une
copie éprouvée, pas une copie laissée vivre.

**Où vivent ces champs** : dans les COLONNES du journal, nommées par `COLUMN_OF_FIELD`, et
jamais dans le bloc de propriétés. Un champ de la racine rangé dans le bloc serait
redéclaré par chaque type d'event, et deux producteurs finiraient par le nommer
différemment — ce que le catalogue de types ne pourrait plus rattraper.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final

ROOT_SCHEMA: Final[dict[str, Any]] = {
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

# La correspondance champ de la racine ↔ colonne du journal, écrite UNE fois. Les quatre
# premières existaient avant la décision du 12/11/2026 sous d'autres noms : le journal
# portait déjà la racine sans le dire. Les trois dernières sont ce que la racine apporte —
# et `ExternalId` répond exactement à une décision de l'epic qui n'avait pas de support :
# « quand la modification vient d'un message reçu, l'event consigne l'identifiant de ce
# message, stable à travers les ré-émissions ».
#
# `DedupKey` a sa colonne mais AUCUN producteur, et c'est délibéré : « on gérera la clef de
# dédoublonnage plus tard » (Gael, 12/11/2026). Elle existe parce qu'elle est dans la
# racine, pas parce qu'on s'en sert — une colonne que personne n'écrit ressemble sinon à un
# oubli, et le prochain lecteur la câblerait sur ce qu'il a sous la main. Le candidat le
# plus proche serait justement le pire : le nonce de l'enveloppe d'appel est NEUF à chaque
# envoi, donc deux émissions du même message auraient deux clés et se dédoubleraient toutes
# les deux. Quand le sujet sera repris, c'est le producteur qui dira sur quoi elle porte.
COLUMN_OF_FIELD: Final[Mapping[str, str]] = {
    "Name": "type",
    "Uuid": "id",
    "EventDate": "functional_at",
    "IntegrationDate": "written_at",
    "ExternalId": "external_id",
    "CreationDate": "creation_date",
    "DedupKey": "dedup_key",
}

ROOT_FIELDS: Final[frozenset[str]] = frozenset(ROOT_SCHEMA["properties"])

# Ce que Miles ajoute autour de la racine et qu'urban-workflow ne connaît pas : l'auteur
# `(annuaire, sub)`, les objets concernés et leur numéro de séquence, et la provenance de
# la date fonctionnelle. Nommé ici pour que la lecture de `COLUMN_OF_FIELD` ne laisse pas
# croire que les autres colonnes du journal sont un oubli.
OUTSIDE_ROOT: Final[tuple[str, ...]] = (
    "author_directory",
    "author_subject",
    "functional_at_source",
    "object_kind",
    "object_id",
    "sequence",
)


class EventNotion(StrEnum):
    """Les notions d'event que Gael distingue (12/11/2026), dans ses mots.

    Elles ne changent ni la racine ni la table : elles disent **de quoi un type d'event
    parle**, ce qu'aucun nom de type ne dit de façon fiable. Un type d'event en porte une
    et une seule, et il n'y a pas de notion par défaut — c'est le catalogue des types
    (story 3f4905bf) qui l'exige à la déclaration.
    """

    # « des évènements techniques du backoffice permettant de traiter des sujets
    # backoffice » : tout ce que trace l'atelier aujourd'hui.
    BACKOFFICE = "backoffice_technique"
    # « des evènements techniques permettant aux socles des devices de fonctionner ».
    DEVICE_SOCLE = "device_technique"
    # « des evènements fonctionnels venant des devices pour appliquer la configuration que
    # nous allons déployer ».
    DEVICE_FONCTIONNEL = "device_fonctionnel"
