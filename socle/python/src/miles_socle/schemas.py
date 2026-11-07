"""Où sont les SOUS-SCHÉMAS dans un schéma JSON, et jusqu'où on descend.

Trois tables, et elles sont ici parce que **deux produits en dépendent** : le module de
paramétrage, qui dérive les modèles d'un contrat OpenAPI en les réécrivant
(`contracts/derived.py`), et le module d'environnement, qui énumère les mots-clés d'un
modèle pour décider s'il peut le confier à un validateur compilé
(`ingestion/conformance.py`). Dupliquées, elles auraient divergé au premier mot-clé ajouté
par une révision du dialecte — et la divergence aurait été silencieuse des deux côtés.

**Un parcours aveugle d'un schéma est FAUX, et c'est tout l'objet de ces tables.** Dans
`{"properties": {"items": {"type": "string"}}}`, le mot `items` est un NOM DE PROPRIÉTÉ,
pas un mot-clé. Descendre partout réécrirait la propriété d'un tiers comme si c'était un
sous-schéma ; énumérer partout prendrait son nom pour un mot-clé. Les tables disent, pour
chaque mot-clé, si sa valeur est un schéma, une liste de schémas, ou une table de schémas
indexée par des noms qui n'en sont pas.
"""

from __future__ import annotations

# Mots-clés dont la valeur est UN schéma.
SCHEMA_VALUE = (
    "items",
    "additionalProperties",
    "not",
    "if",
    "then",
    "else",
    "contains",
    "propertyNames",
    "unevaluatedItems",
    "unevaluatedProperties",
    "contentSchema",
)

# Mots-clés dont la valeur est une LISTE de schémas.
SCHEMA_LIST = ("allOf", "anyOf", "oneOf", "prefixItems")

# Mots-clés dont la valeur est une TABLE de schémas, dont les clés sont des noms.
SCHEMA_TABLE = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")

# Borne de la descente : un schéma de tiers démesurément imbriqué est refusé, nommé,
# plutôt que d'épuiser la pile du back-office.
MAX_SCHEMA_DEPTH = 64
