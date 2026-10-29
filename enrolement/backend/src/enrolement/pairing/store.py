from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from miles_socle.secrets.crypto import Sealed
from miles_socle.signing.keys import ALGORITHM

from enrolement.pairing.model import EnvironmentRef, PairingRequest

# L'environnement désigné est relu par sous-requêtes corrélées, et ses colonnes sont
# écrites LITTÉRALEMENT dans chaque requête : les écritures rendent leur ligne par
# `RETURNING`, qui ne joint pas, et une constante partagée qu'on interpole dans du SQL est
# une faute, pas un raccourci. Ce fichier et `store_peers.py` répètent donc les mêmes
# listes de colonnes, et c'est voulu — les factoriser serait la faute, pas le progrès.

# `module_identity` est lue et écrite par le socle (`miles_socle.signing.identity_store`) :
# la table est déclarée par la migration de CE produit, les requêtes sont au socle, qui
# les sert aux trois. Ne reste ici que l'appariement, qui n'appartient qu'à l'enrôlement.

# Les DEMANDES en attente. Les appariements conclus et leurs pierres tombales sont dans
# `store_peers.py` : deux tables, deux cycles de vie — une demande est éphémère et se
# brûle, un appariement persiste jusqu'à sa révocation.


class PairingDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


def environment_ref_from_row(row: Any) -> EnvironmentRef | None:
    """L'environnement désigné, ou rien. Construit depuis l'identifiant, jamais du slug.

    Le slug est renommable : un environnement dont le libellé et le slug seraient vides
    n'existe pas, mais c'est l'identifiant qui dit s'il y a une désignation.
    """
    environment_id = row["environment_id"]
    if environment_id is None:
        return None
    return EnvironmentRef(environment_id, row["environment_slug"], row["environment_label"])


def _request(row: Any) -> PairingRequest:
    return PairingRequest(
        row["base_url"],
        row["public_key"],
        row["algorithm"],
        row["created_at"],
        row["expires_at"],
        row["name"],
        environment_ref_from_row(row),
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
    name: str,
) -> PairingRequest:
    """Ouvre la demande, ou RENOUVELLE celle qui existe pour la même origine.

    Jamais deux demandes pour une même origine : l'humain ne saurait laquelle accepter, et
    le second code rendrait le premier ambigu. Le renouvellement remplace aussi le secret
    et la clé publique déposée — frapper à nouveau, c'est repartir de zéro.

    SAUF l'environnement désigné, qui SURVIT au renouvellement et, à la première demande,
    est HÉRITÉ de l'appariement déjà conclu sous cette origine. C'est ce qui fait tenir
    deux règles à la fois sans cas particulier ailleurs : une stack qui refrappe pendant
    qu'on la désignait ne fait pas perdre le choix à l'humain — qui ne saurait pas
    pourquoi son code a cessé d'être révélable —, et une stack qui tourne ses clés
    réapparie le MÊME environnement, jamais un autre — un ré-appariement n'est pas
    l'occasion d'en changer. En changer est un geste à part, qui porte sur l'appariement et
    non sur la demande, et qui n'est ouvert que tant qu'aucun device n'est en jeu
    (`resolve_set_peer_environment`).
    """
    row = await db.fetchrow(
        "INSERT INTO pairing_request (base_url, public_key, algorithm, key_version, nonce,"
        " ciphertext, created_at, expires_at, name, environment_id)"
        " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9,"
        " (SELECT p.environment_id FROM environment_peer p WHERE p.base_url = $1))"
        " ON CONFLICT (base_url) DO UPDATE SET public_key = excluded.public_key,"
        " algorithm = excluded.algorithm, key_version = excluded.key_version,"
        " nonce = excluded.nonce, ciphertext = excluded.ciphertext,"
        " created_at = excluded.created_at, expires_at = excluded.expires_at,"
        " name = excluded.name"
        " RETURNING base_url, public_key, algorithm, created_at, expires_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_label",
        base_url,
        public_key,
        ALGORITHM,
        sealed.key_version,
        sealed.nonce,
        sealed.ciphertext,
        now,
        expires_at,
        name,
    )
    return _request(row)


async def db_get_request(db: PairingDb, base_url: str) -> tuple[PairingRequest, Sealed] | None:
    """La demande et son secret scellé. Le secret ne sort d'ici que scellé."""
    row = await db.fetchrow(
        "SELECT base_url, public_key, algorithm, created_at, expires_at, name,"
        " key_version, nonce, ciphertext, environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_label"
        " FROM pairing_request WHERE base_url = $1",
        base_url,
    )
    if row is None:
        return None
    return _request(row), Sealed(row["key_version"], row["nonce"], row["ciphertext"])


async def db_list_requests(db: PairingDb, /) -> list[PairingRequest]:
    rows = await db.fetch(
        "SELECT base_url, public_key, algorithm, created_at, expires_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_label"
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


async def db_designate_request_environment(
    db: PairingDb, base_url: str, environment_id: UUID
) -> PairingRequest | None:
    """Pose l'environnement désigné sur une demande en attente. Nul si elle n'existe plus.

    Écrase sans condition : tant que l'appariement n'est pas conclu, changer d'avis est
    libre, et une désignation qui se verrouillerait au premier clic obligerait à refuser
    la demande pour corriger une erreur de liste déroulante.

    Si l'environnement n'existe pas, la clé étrangère refuse — c'est elle qui tient la
    garde, et non une lecture préalable entre laquelle et l'écriture une suppression
    concurrente passerait.
    """
    row = await db.fetchrow(
        "UPDATE pairing_request SET environment_id = $2 WHERE base_url = $1"
        " RETURNING base_url, public_key, algorithm, created_at, expires_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = pairing_request.environment_id)"
        " AS environment_label",
        base_url,
        environment_id,
    )
    return None if row is None else _request(row)
