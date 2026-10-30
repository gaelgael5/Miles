from __future__ import annotations

from datetime import datetime
from typing import Any

from miles_socle.secrets.crypto import Sealed

from enrolement.pairing.confided_git_model import (
    ConfidedConnection,
    ConfidedWorkspaceRef,
)
from enrolement.pairing.store import PairingDb

# Les connexions git confiées par le module de paramétrage (ticket edcf78bc). Comme dans
# `store.py` et `store_peers.py`, les listes de colonnes sont écrites littéralement dans
# chaque requête : les factoriser rendrait illisible ce que chacune touche, et c'est
# justement ce qu'on vient vérifier quand une ligne est fausse.

_CONNECTION_COLUMNS = (
    "id, label, base_url, confided_at, renewed_at FROM confided_git_connection"
    " WHERE peer_base_url = $1"
)


async def db_lock_confided(db: PairingDb, peer_base_url: str) -> None:
    """Sérialise les transmissions d'un même pair, pour la durée de la TRANSACTION.

    Deux transmissions simultanées liraient la même révision détenue avant que l'une
    l'ait écrite, et la plus ancienne pourrait passer après. Un verrou consultatif et non
    un `SELECT … FOR UPDATE` : à la toute première transmission il n'existe aucune ligne
    d'état à verrouiller, et deux insertions concurrentes se heurteraient alors sur la clé
    primaire — un 500 là où il faut un refus.
    """
    await db.execute("SELECT pg_advisory_xact_lock(hashtext($1))", peer_base_url)


async def db_get_revision(db: PairingDb, peer_base_url: str) -> int | None:
    """La révision détenue, ou rien si ce pair n'a jamais rien confié."""
    row = await db.fetchrow(
        "SELECT revision FROM confided_git_state WHERE peer_base_url = $1", peer_base_url
    )
    return None if row is None else int(row["revision"])


async def db_upsert_state(
    db: PairingDb, peer_base_url: str, species: str, revision: int, now: datetime
) -> None:
    await db.execute(
        "INSERT INTO confided_git_state (peer_base_url, species, revision, received_at)"
        " VALUES ($1, $2, $3, $4)"
        " ON CONFLICT (peer_base_url) DO UPDATE SET revision = excluded.revision,"
        " received_at = excluded.received_at",
        peer_base_url,
        species,
        revision,
        now,
    )


async def db_get_sealed(db: PairingDb, peer_base_url: str, connection_id: str) -> Sealed | None:
    """Le credential chiffré d'une connexion confiée. Jamais lu pour être rendu au-dehors."""
    row = await db.fetchrow(
        "SELECT key_version, nonce, ciphertext FROM confided_git_connection"
        " WHERE peer_base_url = $1 AND id = $2",
        peer_base_url,
        connection_id,
    )
    if row is None:
        return None
    return Sealed(row["key_version"], row["nonce"], row["ciphertext"])


async def db_upsert_connection(
    db: PairingDb,
    peer_base_url: str,
    species: str,
    connection_id: str,
    label: str,
    base_url: str,
    sealed: Sealed,
    now: datetime,
    renewed: bool,
) -> None:
    """Écrit la connexion confiée. Le credential est REMPLACÉ EN PLACE, jamais recréé.

    Jamais de suppression suivie d'une insertion : une lecture qui tomberait dans
    l'intervalle ne trouverait rien et échouerait en « connexion inconnue », ce qui
    enverrait le diagnostic vers une suppression à la source alors que le credential vient
    seulement d'être renouvelé (critère 5 du ticket).

    `confided_at` est conservé au conflit — il date le premier confiage, qui reste un fait —
    et `renewed_at` n'avance QUE si le credential a réellement changé : une transmission qui
    ne change rien ne doit pas faire croire à un renouvellement.
    """
    await db.execute(
        "INSERT INTO confided_git_connection (peer_base_url, species, id, label, base_url,"
        " key_version, nonce, ciphertext, confided_at, renewed_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL)"
        " ON CONFLICT (peer_base_url, id) DO UPDATE SET label = excluded.label,"
        " base_url = excluded.base_url, key_version = excluded.key_version,"
        " nonce = excluded.nonce, ciphertext = excluded.ciphertext,"
        " renewed_at = CASE WHEN $10 THEN $9 ELSE confided_git_connection.renewed_at END",
        peer_base_url,
        species,
        connection_id,
        label,
        base_url,
        sealed.key_version,
        sealed.nonce,
        sealed.ciphertext,
        now,
        renewed,
    )


async def db_delete_absent_connections(
    db: PairingDb, peer_base_url: str, kept: list[str]
) -> list[str]:
    """Détruit les connexions absentes de l'état transmis, et rend leurs identifiants.

    C'est tout le mécanisme de la SUPPRESSION (critère 9) : elle n'a pas de message à
    elle, elle est l'absence. Détruites, jamais marquées inactives — une ligne inactive
    porte encore le credential, et un jour quelqu'un la relit.
    """
    rows = await db.fetch(
        "DELETE FROM confided_git_connection WHERE peer_base_url = $1"
        " AND NOT (id = ANY($2::text[])) RETURNING id",
        peer_base_url,
        kept,
    )
    return [row["id"] for row in rows]


async def db_insert_workspaces(
    db: PairingDb,
    peer_base_url: str,
    connection_id: str,
    workspaces: list[tuple[str, str | None]],
) -> None:
    """Pose les workspaces d'une connexion. `db_delete_workspaces` a nettoyé avant.

    Supprimés puis réinsérés, et ici c'est sans danger : ces lignes ne portent aucun
    secret, et la transaction les rend indivisibles pour toute lecture.
    """
    for workspace_id, repo_url in workspaces:
        await db.execute(
            "INSERT INTO confided_git_workspace (peer_base_url, id, connection_id, repo_url)"
            " VALUES ($1, $2, $3, $4)",
            peer_base_url,
            workspace_id,
            connection_id,
            repo_url,
        )


async def db_delete_workspaces(db: PairingDb, peer_base_url: str) -> None:
    """Vide la liste des workspaces du pair avant de la réécrire en entier.

    Pourquoi tout vider plutôt que connexion par connexion : un workspace qui PASSE d'une
    connexion à une autre resterait sinon sur les deux, et la clé primaire (pair,
    workspace) ferait échouer son insertion — donc une transmission par ailleurs valide.
    L'ordre des connexions dans la charge ne garantit rien là-dessus.
    """
    await db.execute("DELETE FROM confided_git_workspace WHERE peer_base_url = $1", peer_base_url)


async def db_parametrage_peer(db: PairingDb) -> str | None:
    """L'origine du module de paramétrage apparié, s'il y en a un. Il n'en existe qu'un."""
    row = await db.fetchrow("SELECT base_url FROM environment_peer WHERE species = 'parametrage'")
    return None if row is None else str(row["base_url"])


async def db_count_confided(db: PairingDb, peer_base_url: str) -> int:
    row = await db.fetchrow(
        "SELECT count(*) AS n FROM confided_git_connection WHERE peer_base_url = $1",
        peer_base_url,
    )
    return 0 if row is None else int(row["n"])


async def db_get_state_row(db: PairingDb, peer_base_url: str) -> tuple[int, datetime] | None:
    row = await db.fetchrow(
        "SELECT revision, received_at FROM confided_git_state WHERE peer_base_url = $1",
        peer_base_url,
    )
    return None if row is None else (int(row["revision"]), row["received_at"])


async def db_list_confided(db: PairingDb, peer_base_url: str) -> tuple[ConfidedConnection, ...]:
    rows = await db.fetch("SELECT " + _CONNECTION_COLUMNS + " ORDER BY label, id", peer_base_url)
    par_connexion = await _db_workspaces(db, peer_base_url)
    return tuple(_connection(row, par_connexion) for row in rows)


async def db_get_confided(
    db: PairingDb, peer_base_url: str, connection_id: str
) -> ConfidedConnection | None:
    row = await db.fetchrow(
        "SELECT " + _CONNECTION_COLUMNS + " AND id = $2", peer_base_url, connection_id
    )
    if row is None:
        return None
    return _connection(row, await _db_workspaces(db, peer_base_url))


async def _db_workspaces(
    db: PairingDb, peer_base_url: str
) -> dict[str, tuple[ConfidedWorkspaceRef, ...]]:
    """Tous les workspaces du pair, rangés par connexion. Une requête, pas une par ligne."""
    rows = await db.fetch(
        "SELECT connection_id, id, repo_url FROM confided_git_workspace"
        " WHERE peer_base_url = $1 ORDER BY id",
        peer_base_url,
    )
    par_connexion: dict[str, tuple[ConfidedWorkspaceRef, ...]] = {}
    for row in rows:
        reference = ConfidedWorkspaceRef(row["id"], row["repo_url"])
        par_connexion[row["connection_id"]] = (
            *par_connexion.get(row["connection_id"], ()),
            reference,
        )
    return par_connexion


def _connection(
    row: Any, par_connexion: dict[str, tuple[ConfidedWorkspaceRef, ...]]
) -> ConfidedConnection:
    return ConfidedConnection(
        row["id"],
        row["label"],
        row["base_url"],
        row["confided_at"],
        row["renewed_at"],
        par_connexion.get(row["id"], ()),
    )
