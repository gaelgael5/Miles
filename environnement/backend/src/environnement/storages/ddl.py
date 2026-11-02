"""Le SQL d'une table de storage : sa création, et son alignement sur la déclaration.

Module PUR — il ne touche ni base ni disque. C'est ce qui permet de le mettre entièrement
sous test, et c'est nécessaire : le texte qu'il produit s'exécute sur la base d'un
environnement, et il est dérivé d'un paramétrage **venu du réseau**.

**Aucune identité SQL n'est construite par concaténation d'une valeur non validée.** Tout
nom qui entre dans une instruction passe par `quoted`, qui refuse ce qui n'est pas un nom
et double les guillemets de ce qui en est un. PostgreSQL n'a pas de requête paramétrée
pour du DDL : la validation est donc la seule barrière, et elle est ici.
"""

from __future__ import annotations

import re

from environnement.storages.model import FIXED_COLUMNS, FIXED_NAMES, Projection, StorageTable

# 63 octets : la limite de PostgreSQL pour un nom. Au-delà, il TRONQUE en silence — deux
# noms longs se retrouveraient confondus sans qu'aucune erreur ne le dise.
MAX_IDENTIFIER = 63
# Ce qu'on accepte comme nom, avant de le citer : le vocabulaire des noms du paramétrage
# (minuscules, chiffres, tiret, souligné). Volontairement plus strict que ce que
# PostgreSQL accepte entre guillemets — on n'a aucune raison de poser une table nommée
# avec un espace ou un point-virgule, et refuser ferme la porte plutôt que de la citer.
IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
# Préfixe des index que CE module pose. C'est lui qui autorise à en supprimer : un index
# sans ce préfixe a été posé par quelqu'un d'autre, et on n'y touche pas.
INDEX_MARK = "__"
KEY_INDEX = "cle"

# Du vocabulaire de types de l'arbre des propriétés vers le type SQL retenu.
#
# **On ne type que ce que le modèle prouve** (décision du 26/10/2026) : tout le reste est
# `text`. Un `::bigint` sur une valeur non convertible ne casse pas une ligne, il casse
# l'AJOUT de la colonne sur des données déjà là — donc un déploiement.
#
# Une date reste `text`, et ce n'est pas un pis-aller : `format: date-time` est une
# annotation JSON Schema, pas une garantie, et l'ordre lexicographique d'un ISO-8601 est
# son ordre chronologique. Les comparaisons et les intervalles fonctionnent donc.
SQL_TYPES = {
    "string": "text",
    "integer": "bigint",
    "number": "numeric",
    "boolean": "boolean",
}
# Un chemin qui désigne un conteneur ne fait pas une colonne : `#>>` en rendrait le JSON
# sérialisé, sur lequel aucun filtre attendu n'a de sens.
CONTAINER_KINDS = frozenset({"object", "array"})


class IdentifierError(ValueError):
    """Un nom que l'on refuse de poser en base, plutôt que de le citer."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def quoted(name: str) -> str:
    """Un nom validé puis cité. Lève plutôt que de produire du SQL douteux."""
    if not IDENTIFIER_RE.match(name) or len(name.encode("utf-8")) > MAX_IDENTIFIER:
        raise IdentifierError(name)
    # Le doublement est sans objet pour ce que le motif accepte, et il est écrit quand
    # même : le jour où le motif s'élargit, la citation reste juste.
    return '"' + name.replace('"', '""') + '"'


def column_of(keys: tuple[str, ...]) -> str:
    """Le nom de colonne d'un chemin de propriétés : « Contact.Phone » → contact_phone.

    Dérivé et non déclaré, parce que rien dans le paramétrage ne le porte. Deux chemins
    différents peuvent se réduire au même nom — « Contact.Phone » et « contact_phone » —
    et c'est le rôle de l'appelant de refuser la collision, pas le nôtre de la masquer en
    inventant un suffixe que personne ne pourrait relier à son chemin.
    """
    reduit = re.sub(r"[^a-z0-9]+", "_", "_".join(keys).lower()).strip("_")
    return reduit[:MAX_IDENTIFIER]


def sql_type_of(kind: str) -> str | None:
    """Le type SQL d'un type de modèle ; None si le chemin ne fait pas une colonne."""
    if kind in CONTAINER_KINDS:
        return None
    # Une union (« string|null ») n'est pas dans la table : elle ne prouve rien d'autre
    # que la nullité, que toute colonne dérivée porte déjà.
    return SQL_TYPES.get(kind, "text")


def derivation(projection: Projection) -> str:
    """L'expression que PostgreSQL évaluera pour dériver la colonne du jsonb."""
    chemin = _path_literal(projection.keys)
    if projection.sql_type == "text":
        return f"objet #>> {chemin}"
    # La conversion est explicite et le type est celui que le modèle garantit : voir
    # SQL_TYPES pour la raison de ne pas aller plus loin.
    return f"(objet #>> {chemin})::{projection.sql_type}"


def _path_literal(keys: tuple[str, ...]) -> str:
    """Le chemin en littéral `text[]` de PostgreSQL, échappé deux fois.

    Deux niveaux d'échappement, et les oublier produirait du SQL que le paramétrage
    contrôle : les guillemets et les contre-obliques pour le littéral de tableau, puis
    les apostrophes pour la chaîne SQL qui le porte.
    """
    elements = ",".join('"' + k.replace("\\", "\\\\").replace('"', '\\"') + '"' for k in keys)
    return "'{" + elements.replace("'", "''") + "}'"


def index_name(table: str, declared: str) -> str:
    """Le nom d'un index posé par ce module : préfixé par sa table, et marqué."""
    return f"{table}{INDEX_MARK}{declared}"


def is_ours(table: str, name: str) -> bool:
    return name.startswith(f"{table}{INDEX_MARK}")


def create_schema(table: StorageTable) -> str:
    return f"create schema if not exists {quoted(table.schema)}"


def create_table(table: StorageTable) -> str:
    """La table entière, colonnes dérivées comprises. Rejouable : `if not exists`."""
    lignes = [f"  {quoted(name)} {kind}{_contraintes(name)}" for name, kind in FIXED_COLUMNS]
    lignes += [f"  {_column_clause(p)}" for p in table.projections]
    corps = ",\n".join(lignes)
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    return f"create table if not exists {cible} (\n{corps}\n)"


def _contraintes(name: str) -> str:
    if name == "id":
        return " generated always as identity primary key"
    if name == "origine":
        return " not null default 'import'"
    if name in ("vu_le", "modifie_le"):
        return " not null default now()"
    if name == "version_modele":
        # Pas de défaut : c'est l'ingestion qui sait quelle version du modèle elle a
        # validée, et un défaut à zéro ferait croire qu'on le sait.
        return " not null"
    return " not null"


def _column_clause(projection: Projection) -> str:
    """Une colonne dérivée. `stored` : calculée à l'écriture, indexable, jamais écrite."""
    return (
        f"{quoted(projection.column)} {projection.sql_type} "
        f"generated always as ({derivation(projection)}) stored"
    )


def create_indexes(table: StorageTable) -> list[str]:
    """L'index unique de la clé, puis les index déclarés, dans l'ordre déclaré."""
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    unique = quoted(index_name(table.table, KEY_INDEX))
    instructions = [f"create unique index if not exists {unique} on {cible} ({quoted('cle')})"]
    for item in table.indexes:
        nom = quoted(index_name(table.table, item.name))
        colonnes = ", ".join(quoted(c) for c in item.columns)
        instructions.append(f"create index if not exists {nom} on {cible} ({colonnes})")
    return instructions


def statements_for(table: StorageTable) -> list[str]:
    """Tout le SQL d'une table neuve, dans l'ordre où il s'exécute."""
    return [create_schema(table), create_table(table), *create_indexes(table)]


def add_column(table: StorageTable, projection: Projection) -> str:
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    return f"alter table {cible} add column if not exists {_column_clause(projection)}"


def drop_column(table: StorageTable, column: str) -> str:
    """Retire une colonne DÉRIVÉE. L'appelant a la charge de n'appeler que pour celles-là.

    Sans danger pour la donnée, et c'est tout l'intérêt de la forme retenue : la colonne
    est une fonction de `objet`, donc la supprimer ne retire rien — elle se recrée à
    l'identique, et PostgreSQL recalcule ses valeurs sur les lignes déjà là.
    """
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    return f"alter table {cible} drop column if exists {quoted(column)}"


def drop_index(schema: str, name: str) -> str:
    return f"drop index if exists {quoted(schema)}.{quoted(name)}"
