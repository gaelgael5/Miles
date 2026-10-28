from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from miles_socle.signing.identity_model import SINGLETON
from miles_socle.signing.keys import ALGORITHM

from environnement.identity.model import EnrolmentPeer, PairingAttempt

# `module_identity` est lue et écrite par le socle (`miles_socle.signing.identity_store`) :
# la table est déclarée par la migration de CE produit, les requêtes sont au socle, qui
# les sert aux trois. Ne reste ici que ce qui n'appartient qu'à l'environnement — son pair.


class PeerDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


async def db_get_peer(db: PeerDb, /) -> EnrolmentPeer | None:
    row = await db.fetchrow(
        "SELECT base_url, public_key, algorithm, created_at, updated_at FROM enrolment_peer"
        " WHERE id = $1",
        SINGLETON,
    )
    if row is None:
        return None
    return EnrolmentPeer(
        row["base_url"],
        row["public_key"],
        row["algorithm"],
        row["created_at"],
        row["updated_at"],
    )


async def db_upsert_peer(
    db: PeerDb, base_url: str, public_key: str, now: datetime
) -> EnrolmentPeer:
    """Enregistre le pair, ou REMPLACE celui qui existe — jamais un second.

    Le remplacement est le ré-appariement : il ne doit pas laisser deux identités pour une
    stack. `created_at` est conservé, parce qu'il date l'appariement initial, qui reste un
    fait même après rotation des clés.
    """
    row = await db.fetchrow(
        "INSERT INTO enrolment_peer (id, base_url, public_key, algorithm, created_at,"
        " updated_at) VALUES ($1, $2, $3, $4, $5, $5)"
        " ON CONFLICT (id) DO UPDATE SET base_url = excluded.base_url,"
        " public_key = excluded.public_key, algorithm = excluded.algorithm,"
        " updated_at = excluded.updated_at"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at",
        SINGLETON,
        base_url,
        public_key,
        ALGORITHM,
        now,
    )
    return EnrolmentPeer(
        row["base_url"],
        row["public_key"],
        row["algorithm"],
        row["created_at"],
        row["updated_at"],
    )


async def db_get_attempt(db: PeerDb, /) -> PairingAttempt | None:
    row = await db.fetchrow(
        "SELECT base_url, created_at FROM pairing_attempt WHERE id = $1", SINGLETON
    )
    return None if row is None else PairingAttempt(row["base_url"], row["created_at"])


async def db_upsert_attempt(db: PeerDb, base_url: str, now: datetime) -> PairingAttempt:
    """Ouvre la tentative, ou REMPLACE celle qui traînait.

    Frapper ailleurs abandonne la demande précédente : garder les deux laisserait l'humain
    coller un code sans savoir chez qui il part, et une seule des deux peut aboutir de
    toute façon — un environnement n'a qu'un module d'enrôlement.
    """
    row = await db.fetchrow(
        "INSERT INTO pairing_attempt (id, base_url, created_at) VALUES ($1, $2, $3)"
        " ON CONFLICT (id) DO UPDATE SET base_url = excluded.base_url,"
        " created_at = excluded.created_at"
        " RETURNING base_url, created_at",
        SINGLETON,
        base_url,
        now,
    )
    return PairingAttempt(row["base_url"], row["created_at"])


async def db_delete_attempt(db: PeerDb, /) -> bool:
    """Referme la tentative. Rend faux s'il n'y en avait pas."""
    return await db.execute("DELETE FROM pairing_attempt WHERE id = $1", SINGLETON) != "DELETE 0"
