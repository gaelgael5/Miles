from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from miles.gitaccess.confide_model import ConfidedSnapshot, ConnectionToConfide, WorkspaceToConfide

# Ce qu'on transmet au module d'enrôlement, et la trace de ce qu'on lui a transmis
# (ticket edcf78bc). Comme ailleurs dans le dépôt, les listes de colonnes sont écrites
# littéralement : c'est ce qu'on vient lire quand une ligne transmise est fausse.


class ConfideDb(Protocol):
    """Pool ou connexion : les lectures se font sur l'un, les écritures dans la transaction
    de l'autre. Un Protocol comme ailleurs dans le dépôt — le proxy de connexion d'un pool
    n'est ni l'un ni l'autre des types concrets d'asyncpg."""

    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...
    async def fetchval(self, query: str, *args: Any) -> Any: ...


async def db_next_revision(db: ConfideDb) -> int:
    """Alloue la révision de CETTE transmission, au moment où l'on lit l'état.

    Allouée avec la lecture et non à l'envoi : c'est le couple (état lu, révision) qui doit
    être cohérent. Une révision prise après la lecture pourrait dépasser celle d'une
    transmission partie entre-temps avec un état plus récent.
    """
    return int(await db.fetchval("SELECT nextval('confided_git_revision')"))


async def db_snapshot(db: ConfideDb) -> tuple[ConnectionToConfide, ...]:
    """L'état complet des connexions git, avec les workspaces qui s'en servent.

    La date de modification du PAT vient de la table des secrets : c'est elle qui fait
    changer l'empreinte quand un credential est remplacé, sans qu'aucune empreinte de
    secret n'ait à être calculée ni stockée.
    """
    connexions = await db.fetch(
        "SELECT c.id, c.label, c.base_url, c.token_secret_slug, s.updated_at AS token_updated_at"
        " FROM git_connections c JOIN secrets s ON s.slug = c.token_secret_slug"
        " ORDER BY c.id"
    )
    workspaces = await db.fetch(
        "SELECT id, git_connection_id, repo_url FROM workspaces"
        " WHERE git_connection_id IS NOT NULL ORDER BY id"
    )
    par_connexion: dict[str, tuple[WorkspaceToConfide, ...]] = {}
    for row in workspaces:
        connexion = str(row["git_connection_id"])
        par_connexion[connexion] = (
            *par_connexion.get(connexion, ()),
            WorkspaceToConfide(row["id"], row["repo_url"]),
        )
    return tuple(
        ConnectionToConfide(
            row["id"],
            row["label"],
            row["base_url"],
            row["token_secret_slug"],
            row["token_updated_at"],
            par_connexion.get(row["id"], ()),
        )
        for row in connexions
    )


async def db_connections_using(db: ConfideDb, token_secret_slug: str) -> list[str]:
    """Les connexions dont le PAT est ce secret-là. Vide pour tout autre secret.

    C'est ce qui fait qu'un remplacement de valeur dans l'écran des secrets ne déclenche
    une transmission que s'il concerne réellement une connexion git.
    """
    rows = await db.fetch(
        "SELECT id FROM git_connections WHERE token_secret_slug = $1 ORDER BY id",
        token_secret_slug,
    )
    return [row["id"] for row in rows]


async def db_record_transmission(
    db: ConfideDb, peer_base_url: str, snapshot: ConfidedSnapshot, now: datetime
) -> None:
    """Note ce qu'on vient de transmettre, à QUI, et sous quelle révision.

    Écrite seulement après un accusé du destinataire : notée d'avance, elle ferait afficher
    « confiées » pour une transmission qui n'est jamais arrivée, et c'est précisément la
    divergence que cette table existe pour rendre visible.
    """
    await db.execute(
        "INSERT INTO confided_git_transmission (peer_base_url, revision, content_digest,"
        " transmitted_at) VALUES ($1, $2, $3, $4)"
        " ON CONFLICT (peer_base_url) DO UPDATE SET revision = excluded.revision,"
        " content_digest = excluded.content_digest, transmitted_at = excluded.transmitted_at",
        peer_base_url,
        snapshot.revision,
        snapshot.digest,
        now,
    )


async def db_get_transmission(db: ConfideDb) -> tuple[int, str, datetime] | None:
    """La dernière transmission faite AU PAIR COURANT, par jointure sur son origine.

    La jointure PORTE l'invariant : réapparié à une autre origine, on n'a rien transmis à
    celle-là, et la lecture rend donc rien — ce qui fait dire à l'écran « à transmettre »
    au lieu d'afficher la date d'un confiage fait à quelqu'un d'autre. L'invariant n'est pas
    une clause qu'on peut oublier d'écrire, c'est la jointure elle-même (leçon du
    29/10/2026).
    """
    row = await db.fetchrow(
        "SELECT t.revision, t.content_digest, t.transmitted_at"
        " FROM confided_git_transmission t"
        " JOIN enrolment_peer p ON p.base_url = t.peer_base_url"
        " WHERE p.id = 'self'"
    )
    if row is None:
        return None
    return int(row["revision"]), str(row["content_digest"]), row["transmitted_at"]
