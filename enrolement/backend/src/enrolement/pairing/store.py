from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from miles_socle.secrets.crypto import Sealed
from miles_socle.signing.keys import ALGORITHM

from enrolement.pairing.model import EnvironmentPeer, PairingRequest

# `module_identity` est lue et écrite par le socle (`miles_socle.signing.identity_store`) :
# la table est déclarée par la migration de CE produit, les requêtes sont au socle, qui
# les sert aux trois. Ne reste ici que l'appariement, qui n'appartient qu'à l'enrôlement.


class PairingDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


def _request(row: Any) -> PairingRequest:
    return PairingRequest(
        row["base_url"],
        row["public_key"],
        row["algorithm"],
        row["created_at"],
        row["expires_at"],
    )


def _peer(row: Any) -> EnvironmentPeer:
    return EnvironmentPeer(
        row["base_url"],
        row["public_key"],
        row["algorithm"],
        row["created_at"],
        row["updated_at"],
    )


async def db_delete_expired_requests(db: PairingDb, now: datetime) -> tuple[str, ...]:
    """Supprime les demandes échues et rend leurs origines, pour que le journal les nomme.

    Le secret part avec la ligne : c'est ce qui rend l'expiration réelle plutôt que
    cosmétique. Appelée au début de chaque lecture et de chaque écriture, pour qu'aucune
    demande échue ne soit jamais vue vivante — une tâche de fond, elle, laisserait une
    fenêtre pendant laquelle un code périmé serait encore accepté.
    """
    rows = await db.fetch(
        "DELETE FROM pairing_request WHERE expires_at <= $1 RETURNING base_url", now
    )
    return tuple(row["base_url"] for row in rows)


async def db_upsert_request(
    db: PairingDb,
    base_url: str,
    public_key: str,
    sealed: Sealed,
    now: datetime,
    expires_at: datetime,
) -> PairingRequest:
    """Ouvre la demande, ou RENOUVELLE celle qui existe pour la même origine.

    Jamais deux demandes pour une même origine : l'humain ne saurait laquelle accepter, et
    le second code rendrait le premier ambigu. Le renouvellement remplace aussi le secret
    et la clé publique déposée — frapper à nouveau, c'est repartir de zéro.
    """
    row = await db.fetchrow(
        "INSERT INTO pairing_request (base_url, public_key, algorithm, key_version, nonce,"
        " ciphertext, created_at, expires_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)"
        " ON CONFLICT (base_url) DO UPDATE SET public_key = excluded.public_key,"
        " algorithm = excluded.algorithm, key_version = excluded.key_version,"
        " nonce = excluded.nonce, ciphertext = excluded.ciphertext,"
        " created_at = excluded.created_at, expires_at = excluded.expires_at"
        " RETURNING base_url, public_key, algorithm, created_at, expires_at",
        base_url,
        public_key,
        ALGORITHM,
        sealed.key_version,
        sealed.nonce,
        sealed.ciphertext,
        now,
        expires_at,
    )
    return _request(row)


async def db_get_request(db: PairingDb, base_url: str) -> tuple[PairingRequest, Sealed] | None:
    """La demande et son secret scellé. Le secret ne sort d'ici que scellé."""
    row = await db.fetchrow(
        "SELECT base_url, public_key, algorithm, created_at, expires_at,"
        " key_version, nonce, ciphertext FROM pairing_request WHERE base_url = $1",
        base_url,
    )
    if row is None:
        return None
    return _request(row), Sealed(row["key_version"], row["nonce"], row["ciphertext"])


async def db_list_requests(db: PairingDb, /) -> list[PairingRequest]:
    rows = await db.fetch(
        "SELECT base_url, public_key, algorithm, created_at, expires_at"
        " FROM pairing_request ORDER BY created_at"
    )
    return [_request(row) for row in rows]


async def db_delete_request(db: PairingDb, base_url: str) -> bool:
    """Brûle la demande : son secret disparaît avec sa ligne. Rend faux si elle n'existait plus.

    Le booléen n'est pas décoratif — c'est lui qui rend l'usage UNIQUE du code atomique :
    deux confirmations concurrentes passent toutes deux la vérification du code, et seule
    celle dont la suppression a effectivement retiré une ligne poursuit.
    """
    return await db.execute("DELETE FROM pairing_request WHERE base_url = $1", base_url) != (
        "DELETE 0"
    )


async def db_lock_request(db: PairingDb, base_url: str) -> None:
    """Sérialise la confirmation d'une demande, pour la durée de la TRANSACTION.

    Sans ce verrou, deux confirmations simultanées liraient la même demande avant que
    l'une l'ait brûlée. La suppression conditionnelle suffirait à n'en laisser passer
    qu'une ; le verrou évite en plus que la seconde écrive le pair avant d'être refusée.
    """
    await db.execute("SELECT pg_advisory_xact_lock(hashtext($1))", base_url)


async def db_upsert_peer(
    db: PairingDb, base_url: str, public_key: str, now: datetime
) -> EnvironmentPeer:
    """Enregistre l'environnement apparié, ou REMPLACE sa clé — jamais un doublon.

    Le remplacement est le ré-appariement. `created_at` est conservé : il date
    l'appariement initial, qui reste un fait même après rotation des clés.
    """
    row = await db.fetchrow(
        "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at, updated_at)"
        " VALUES ($1, $2, $3, $4, $4)"
        " ON CONFLICT (base_url) DO UPDATE SET public_key = excluded.public_key,"
        " algorithm = excluded.algorithm, updated_at = excluded.updated_at"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at",
        base_url,
        public_key,
        ALGORITHM,
        now,
    )
    return _peer(row)


async def db_get_peer(db: PairingDb, base_url: str) -> EnvironmentPeer | None:
    row = await db.fetchrow(
        "SELECT base_url, public_key, algorithm, created_at, updated_at"
        " FROM environment_peer WHERE base_url = $1",
        base_url,
    )
    return None if row is None else _peer(row)


async def db_list_peers(db: PairingDb, /) -> list[EnvironmentPeer]:
    rows = await db.fetch(
        "SELECT base_url, public_key, algorithm, created_at, updated_at"
        " FROM environment_peer ORDER BY base_url"
    )
    return [_peer(row) for row in rows]
