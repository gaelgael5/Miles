"""Ce que la base porte déjà, et la trace de ce qu'on y a posé.

**Le catalogue de PostgreSQL fait foi sur la forme des tables**, et `storage_schema` ne
porte que ce qu'on a fait. L'inverse — croire la table de trace — ferait répondre « posée »
pour une table qu'une restauration de base aurait emportée, exactement comme croire
`hosted_version` plutôt que `git rev-parse` ferait répondre « à jour » à un volume perdu.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from environnement.storages.model import StorageRefusal, StorageTable


class StorageDb(Protocol):
    """Le strict nécessaire, comme pour l'hébergement : une connexion du pool et une
    connexion simple ne sont pas du même type chez asyncpg, et aucune des deux n'a à
    s'imposer ici."""

    def is_in_transaction(self) -> bool: ...
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...


@dataclass(frozen=True)
class ExistingColumn:
    name: str
    sql_type: str
    generated: bool


@dataclass(frozen=True)
class ExistingTable:
    """Ce que le catalogue dit d'une table de storage. None si elle n'existe pas."""

    columns: tuple[ExistingColumn, ...]
    indexes: tuple[str, ...]

    def column(self, name: str) -> ExistingColumn | None:
        return next((c for c in self.columns if c.name == name), None)


@dataclass(frozen=True)
class Materialised:
    """Une ligne de `storage_schema` : ce qu'on a posé, ou ce qu'on a refusé."""

    storage: str
    schema_name: str | None
    table_name: str | None
    model: str | None
    version_number: int | None
    statements: tuple[str, ...]
    applied_at: datetime | None
    refusal: str | None
    refusal_detail: str | None


async def db_existing_table(conn: StorageDb, schema: str, table: str) -> ExistingTable | None:
    """La forme réelle de la table, lue du catalogue. None si elle n'existe pas.

    `format_type` plutôt que `data_type` : il rend « timestamp with time zone » et
    « bigint » tels que le DDL les écrit, donc comparables sans table de correspondance
    maison — qui aurait divergé au premier type ajouté.
    """
    found = await conn.fetchval(
        "SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = $1 AND c.relname = $2 AND c.relkind = 'r'",
        schema,
        table,
    )
    if found is None:
        return None
    columns = await conn.fetch(
        "SELECT a.attname AS nom, format_type(a.atttypid, a.atttypmod) AS type_sql,"
        " a.attgenerated <> '' AS derivee"
        " FROM pg_attribute a"
        " WHERE a.attrelid = $1 AND a.attnum > 0 AND NOT a.attisdropped"
        " ORDER BY a.attnum",
        found,
    )
    indexes = await conn.fetch(
        "SELECT c.relname AS nom FROM pg_index i"
        " JOIN pg_class c ON c.oid = i.indexrelid"
        " WHERE i.indrelid = $1 ORDER BY c.relname",
        found,
    )
    return ExistingTable(
        columns=tuple(
            ExistingColumn(row["nom"], row["type_sql"], row["derivee"]) for row in columns
        ),
        indexes=tuple(row["nom"] for row in indexes),
    )


async def db_record_applied(
    conn: StorageDb,
    table: StorageTable,
    version_number: int,
    statements: list[str],
    now: datetime,
) -> None:
    """La trace d'un storage posé. Remplace la précédente : c'est un ÉTAT, pas un journal.

    L'historique de ce qui a été appliqué est dans le journal d'events, qui est fait pour
    ça. Empiler ici ferait deux journaux, dont l'un sans rétention.
    """
    await conn.execute(
        "INSERT INTO storage_schema (storage, schema_name, table_name, model,"
        " version_number, statements, applied_at, refusal, refusal_detail)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, NULL, NULL)"
        " ON CONFLICT (storage) DO UPDATE SET schema_name = EXCLUDED.schema_name,"
        " table_name = EXCLUDED.table_name, model = EXCLUDED.model,"
        " version_number = EXCLUDED.version_number, statements = EXCLUDED.statements,"
        " applied_at = EXCLUDED.applied_at, refusal = NULL, refusal_detail = NULL",
        table.storage,
        table.schema,
        table.table,
        table.model,
        version_number,
        json.dumps(statements),
        now,
    )


async def db_record_refusal(conn: StorageDb, refusal: StorageRefusal) -> None:
    """La trace d'un storage refusé, et l'effacement de ce qu'on croyait avoir posé.

    La contrainte du modèle interdit « posé et refusé » à la fois : la ligne redevient
    donc entièrement un refus. La TABLE, elle, n'est pas touchée — une table de données
    ne disparaît pas parce qu'une version la déclare mal.
    """
    await conn.execute(
        "INSERT INTO storage_schema (storage, schema_name, table_name, model,"
        " version_number, statements, applied_at, refusal, refusal_detail)"
        " VALUES ($1, NULL, NULL, NULL, NULL, '[]'::jsonb, NULL, $2, $3)"
        " ON CONFLICT (storage) DO UPDATE SET schema_name = NULL, table_name = NULL,"
        " model = NULL, version_number = NULL, statements = '[]'::jsonb, applied_at = NULL,"
        " refusal = EXCLUDED.refusal, refusal_detail = EXCLUDED.refusal_detail",
        refusal.storage,
        refusal.code,
        refusal.detail,
    )


async def db_materialised(conn: StorageDb) -> list[Materialised]:
    rows = await conn.fetch(
        "SELECT storage, schema_name, table_name, model, version_number, statements,"
        " applied_at, refusal, refusal_detail FROM storage_schema ORDER BY storage"
    )
    return [
        Materialised(
            storage=row["storage"],
            schema_name=row["schema_name"],
            table_name=row["table_name"],
            model=row["model"],
            version_number=row["version_number"],
            statements=tuple(_statements(row["statements"])),
            applied_at=row["applied_at"],
            refusal=row["refusal"],
            refusal_detail=row["refusal_detail"],
        )
        for row in rows
    ]


async def db_forget(conn: StorageDb, kept: list[str]) -> list[str]:
    """Oublie la trace des storages que la version ne déclare plus ; rend leurs noms.

    La TRACE s'oublie, la TABLE reste : un storage retiré d'une déclaration n'emporte pas
    ses données. C'est un geste d'exploitation, pas une conséquence de paramétrage.
    """
    rows = await conn.fetch(
        "DELETE FROM storage_schema WHERE NOT (storage = ANY($1::text[])) RETURNING storage",
        kept,
    )
    return [row["storage"] for row in rows]


def _statements(value: object) -> list[str]:
    # Une colonne jsonb revient d'asyncpg en CHAÎNE : le journal du socle le savait déjà,
    # et une leçon du dépôt porte le jour où un test l'a oublié.
    if isinstance(value, str):
        value = json.loads(value)
    return [str(item) for item in value] if isinstance(value, list) else []
