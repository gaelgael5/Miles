"""Ce qu'une déclaration de storage devient, côté base : une table et ses colonnes.

Le paramétrage dit QUOI stocker ; ce module dit à quoi ça ressemble en PostgreSQL. La
forme est celle posée au cadrage (story « Filtrer un storage sur ses propriétés
déclarées ») : une table par storage, dans le schéma de son domaine, la vérité en jsonb,
et une colonne DÉRIVÉE PAR LA BASE par propriété indexable.
"""

from __future__ import annotations

from dataclasses import dataclass

from miles_socle.events.catalog import EventShape, closed_block

# La marque d'absence (Gael, 09/11/2026 : « si clef d'item pas présente, lors d'un import
# full par upload de fichier, l'item est flagué en base »). Une seule colonne pour la
# marque ET sa date : nulle quand l'item est porté par les imports, portant l'instant de
# l'import qui ne l'a pas porté sinon. Deux colonnes — un booléen et une date — auraient
# pu se contredire, et c'est la date qui décide d'une suppression.
ABSENCE_COLUMN = "absent_depuis"

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
    (ABSENCE_COLUMN, "timestamp with time zone"),
)
FIXED_NAMES = frozenset(name for name, _ in FIXED_COLUMNS)

# Les colonnes fixes qu'on sait AJOUTER à une table déjà en service, et donc dont
# l'absence ne fait pas refuser le storage.
#
# **Pourquoi cette liste existe.** Les tables de storage ne sont pas posées par les
# migrations numérotées : elles sont dérivées du paramétrage, et celles qui tournent déjà
# dans un environnement portent la forme du jour où leur version a été servie. Ajouter une
# colonne fixe sans cette distinction aurait fait répondre `table_de_forme_inattendue` à
# CHAQUE storage déjà en service — un refus que rien ne répare, puisque le service signale
# au lieu de corriger.
#
# **Pourquoi celle-ci peut s'ajouter alors que les autres non.** Elle est NULLABLE et sans
# défaut : PostgreSQL 11 et au-delà posent une telle colonne sans réécrire la table, donc
# sans verrou long et sans coût proportionnel au nombre de lignes. Les autres colonnes
# fixes sont `not null` : leur absence n'est pas un retard de version, c'est le signe que
# la table n'est pas une table de storage — et la remplir supposerait de savoir ce qu'elle
# porte, ce qu'on ne sait pas.
ADDABLE_COLUMNS = frozenset({ABSENCE_COLUMN})

# Événements du module : ce qui s'est passé à la pose d'une version.
STORAGES_MATERIALISED_EVENT = "environment.storages_materialised"
STORAGE_REFUSED_EVENT = "environment.storage_refused"
STORAGES_OBJECT_KIND = "storages"
# Déclarés ici, et le catalogue du produit les y prend : un type écrit par le code et
# absent du catalogue fait rendre 500 au premier event, et c'est arrivé le 29/10/2026.
_NOMS: dict[str, object] = {"type": "array", "items": {"type": "string", "minLength": 1}}
EVENT_SHAPES = (
    EventShape(
        STORAGES_MATERIALISED_EVENT,
        "Storages matérialisés",
        closed_block(
            {
                "version": {"type": "integer", "minimum": 1},
                # Ce qui a CHANGÉ, pas ce qui est en place : un journal qui annonce une
                # pose à chaque rejeu ne se lit plus. L'event n'est d'ailleurs écrit que
                # si l'un des trois n'est pas vide.
                "changed": _NOMS,
                "refused": _NOMS,
                "forgotten": _NOMS,
            }
        ),
    ),
    EventShape(
        STORAGE_REFUSED_EVENT,
        "Storage refusé",
        closed_block(
            {
                "version": {"type": "integer", "minimum": 1},
                "storage": {"type": "string", "minLength": 1},
                "refusal": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,39}$"},
                # NUL et non absent : tous les refus n'ont pas de détail, et une absence
                # ferait chercher si le producteur a oublié de le joindre.
                "detail": {"type": ["string", "null"]},
            }
        ),
    ),
)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)

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
class ExpiryRule:
    """Une règle de péremption RÉSOLUE contre le modèle : « la colonne + le délai est passée ».

    Déclarée par l'administrateur sur le storage (`peremption:`, story `5afb7728`) et
    appliquée à la fin d'un import (story `45543845`). Elle est gardée sur la TABLE et non
    relue au moment de supprimer : la colonne ne se dérive pas du chemin déclaré sans le
    modèle, et c'est ici — où il est lu — qu'on sait encore à quoi le chemin renvoyait.

    `path` est le chemin DÉCLARÉ, gardé pour le dire : un refus ou un écran qui nommerait
    `fin_activite` enverrait chercher une colonne interne au lieu de la propriété choisie.
    """

    path: str
    column: str
    days: int


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
    # Les règles de péremption déclarées, résolues contre le modèle. Vide par défaut : un
    # storage sans règle ne se nettoie pas, et un paramétrage déjà écrit ne se met pas à
    # supprimer parce qu'une version l'a traversé.
    expiries: tuple[ExpiryRule, ...] = ()
    # Les règles de péremption qu'on ne sait PLUS évaluer, par le chemin qu'elles nomment :
    # la propriété a disparu du modèle, ou a cessé d'être projetée. Gardées plutôt que
    # tues, et le nettoyage se refuse ENTIÈREMENT sur ce storage tant qu'il en reste une
    # (story `45543845`, critère 10) — une règle de suppression qu'on ne sait plus évaluer
    # ne se rabat pas sur une approximation, et les autres règles du même storage ne
    # tournent pas non plus : on ne sait pas si elles étaient censées porter seules.
    #
    # Le storage, lui, reste SERVI : le refuser rendrait sa table illisible pour une règle
    # qui ne concerne que son nettoyage, ce qui est bien pire que de ne pas nettoyer.
    unresolved_expiries: tuple[str, ...] = ()


@dataclass(frozen=True)
class StorageRefusal:
    """Un storage qu'on ne matérialise pas, et pourquoi. Nommé, jamais tu."""

    storage: str
    code: str
    detail: str | None = None
