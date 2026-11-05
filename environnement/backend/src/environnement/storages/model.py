"""Ce qu'une déclaration de storage devient, côté base : une table et ses colonnes.

Le paramétrage dit QUOI stocker ; ce module dit à quoi ça ressemble en PostgreSQL. La
forme est celle posée au cadrage (story « Filtrer un storage sur ses propriétés
déclarées ») : une table par storage, dans le schéma de son domaine, la vérité en jsonb,
et une colonne DÉRIVÉE PAR LA BASE par propriété indexable.
"""

from __future__ import annotations

from dataclasses import dataclass

# Les colonnes que porte toute table de storage, et leur type. Déclarées ici et nulle
# part ailleurs : c'est contre cette liste qu'on reconnaît une table conforme, et deux
# listes auraient fini par décrire deux formes.
FIXED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("id", "bigint"),
    ("cle", "text"),
    ("objet", "jsonb"),
    ("empreinte", "bytea"),
    ("origine", "text"),
    ("vu_le", "timestamp with time zone"),
    ("modifie_le", "timestamp with time zone"),
    ("version_modele", "integer"),
)
FIXED_NAMES = frozenset(name for name, _ in FIXED_COLUMNS)

# Événements du module : ce qui s'est passé à la pose d'une version.
STORAGES_MATERIALISED_EVENT = "environment.storages_materialised"
STORAGE_REFUSED_EVENT = "environment.storage_refused"
STORAGES_OBJECT_KIND = "storages"
# Déclarés ici, et le catalogue du produit les y prend : un type écrit par le code et
# absent du catalogue fait rendre 500 au premier event, et c'est arrivé le 29/10/2026.
EVENT_TYPES = frozenset({STORAGES_MATERIALISED_EVENT, STORAGE_REFUSED_EVENT})

# Motifs de refus d'un storage. Chacun appelle un geste différent dans le paramétrage,
# donc chacun a son nom — un refus unique les enverrait tous chercher au même endroit.
REFUSAL_UNREADABLE = "declaration_illisible"
REFUSAL_BAD_MODEL = "modele_invalide"
REFUSAL_MODEL_MISSING = "modele_absent"
REFUSAL_BAD_NAME = "nom_invalide"
REFUSAL_UNKNOWN_PROPERTY = "propriete_inconnue"
REFUSAL_NOT_SCALAR = "propriete_non_scalaire"
REFUSAL_COLUMN_CLASH = "colonne_en_collision"
REFUSAL_TOO_MANY_COLUMNS = "trop_de_colonnes"
REFUSAL_INDEX_NAME = "nom_d_index_invalide"
REFUSAL_UNEXPECTED_SHAPE = "table_de_forme_inattendue"
REFUSAL_TYPE_CHANGE = "changement_de_type_requis"
REFUSAL_APPLY_FAILED = "application_refusee"
# Lecture d'un storage dont la table n'est pas à jour de la version servie. Deux refus
# et non un seul : « pas de table du tout » et « table en retard d'une colonne » se
# referment par le même geste, mais ne se diagnostiquent pas pareil — l'un dit qu'aucune
# version n'a jamais été posée ici, l'autre qu'une version plus récente ne l'est pas.
REFUSAL_TABLE_ABSENT = "table_absente"
REFUSAL_TABLE_BEHIND = "table_en_retard"


@dataclass(frozen=True)
class Projection:
    """Une propriété indexable, telle que la base la dérivera.

    `kind` est le type que le MODÈLE annonce, dans le vocabulaire de l'arbre des
    propriétés du portail ; `sql_type` est ce qu'on en retient. Les deux sont gardés :
    le second seul ne dirait plus pourquoi une colonne est en `text`.
    """

    column: str
    keys: tuple[str, ...]
    kind: str
    sql_type: str


@dataclass(frozen=True)
class TableIndex:
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class StorageTable:
    """Un storage déclaré, résolu contre son modèle : prêt à devenir du SQL."""

    storage: str
    label: str
    schema: str
    table: str
    model: str
    projections: tuple[Projection, ...]
    indexes: tuple[TableIndex, ...]
    # Les jpath de la clé fonctionnelle, tels que déclarés. La clé est extraite par
    # l'ingestion, pas par la base : elle n'est pas une colonne dérivée, et c'est voulu —
    # une règle de clé peut porter sur plusieurs chemins et se composer.
    keys: tuple[str, ...]


@dataclass(frozen=True)
class StorageRefusal:
    """Un storage qu'on ne matérialise pas, et pourquoi. Nommé, jamais tu."""

    storage: str
    code: str
    detail: str | None = None
