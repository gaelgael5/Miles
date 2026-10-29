from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from miles_socle.signing.keys import ALGORITHM

from enrolement.pairing.model import EnvironmentPeer
from enrolement.pairing.store import PairingDb, environment_ref_from_row

# Les appariements CONCLUS, et les pierres tombales de ceux qu'on a révoqués. Mêmes
# raisons qu'en tête de `store.py` : les listes de colonnes sont écrites littéralement
# dans chaque requête, et les répétitions entre les deux fichiers ne se factorisent pas.


def _peer(row: Any) -> EnvironmentPeer:
    return EnvironmentPeer(
        row["base_url"],
        row["public_key"],
        row["algorithm"],
        row["created_at"],
        row["updated_at"],
        row["name"],
        environment_ref_from_row(row),
    )


async def db_upsert_peer(
    db: PairingDb,
    base_url: str,
    public_key: str,
    now: datetime,
    name: str | None,
    environment_id: UUID,
) -> EnvironmentPeer:
    """Enregistre l'environnement apparié, ou REMPLACE sa clé — jamais un doublon.

    Le remplacement est le ré-appariement. `created_at` est conservé : il date
    l'appariement initial, qui reste un fait même après rotation des clés.

    L'environnement, lui, est posé à l'insertion et JAMAIS réécrit au conflit : il vient
    de la demande, qui l'a elle-même hérité de cet appariement s'il en portait un. Le
    rattachement d'un appariement hérité passe par `db_attach_peer_environment`, et c'est
    la seule autre voie — déplacer un appariement conclu d'un environnement vers un autre
    reste inexprimable ici, ce qui vaut mieux qu'une garde qu'on peut oublier d'appeler.
    """
    row = await db.fetchrow(
        "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
        " updated_at, name, environment_id) VALUES ($1, $2, $3, $4, $4, $5, $6)"
        " ON CONFLICT (base_url) DO UPDATE SET public_key = excluded.public_key,"
        " algorithm = excluded.algorithm, updated_at = excluded.updated_at,"
        " name = excluded.name"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label",
        base_url,
        public_key,
        ALGORITHM,
        now,
        name,
        environment_id,
    )
    return _peer(row)


async def db_get_peer(db: PairingDb, base_url: str) -> EnvironmentPeer | None:
    row = await db.fetchrow(
        "SELECT base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label"
        " FROM environment_peer WHERE base_url = $1",
        base_url,
    )
    return None if row is None else _peer(row)


async def db_list_peers(db: PairingDb, /) -> list[EnvironmentPeer]:
    rows = await db.fetch(
        "SELECT base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label"
        " FROM environment_peer ORDER BY base_url"
    )
    return [_peer(row) for row in rows]


async def db_attach_peer_environment(
    db: PairingDb, base_url: str, environment_id: UUID, now: datetime
) -> EnvironmentPeer | None:
    """Rattache un appariement HÉRITÉ, conclu avant que la désignation n'existe.

    `environment_id IS NULL` n'est pas une précaution : c'est ce qui rend le DÉPLACEMENT
    inexprimable. Un appariement qui porte déjà un environnement n'est pas rattachable, il
    est à révoquer puis à réapparier — le déplacer emporterait ses devices sans le dire.
    La condition est dans la clause `WHERE` plutôt que dans une lecture qui la précéderait,
    pour que deux rattachements concurrents n'en voient pas tous deux le champ vide.

    Rend nul quand rien n'a bougé, sans dire lequel des deux cas : l'appelant a lu
    l'appariement juste avant et sait le distinguer.
    """
    row = await db.fetchrow(
        "UPDATE environment_peer SET environment_id = $2, updated_at = $3"
        " WHERE base_url = $1 AND environment_id IS NULL"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label",
        base_url,
        environment_id,
        now,
    )
    return None if row is None else _peer(row)


async def db_get_peer_base_url_by_environment(db: PairingDb, environment_id: UUID) -> str | None:
    """L'origine de l'appariement qui porte cet environnement, s'il y en a un.

    Rend l'origine et non l'appariement entier : l'appelant n'a besoin que de savoir si
    c'est LUI qui le porte déjà — un ré-appariement de la même stack — ou quelqu'un
    d'autre, auquel cas il refuse.
    """
    row = await db.fetchrow(
        "SELECT base_url FROM environment_peer WHERE environment_id = $1", environment_id
    )
    return None if row is None else str(row["base_url"])


async def db_delete_peer(db: PairingDb, base_url: str) -> EnvironmentPeer | None:
    """Révoque : la ligne de l'appariement DISPARAÎT, et sa clé publique avec elle.

    Une suppression, pas un drapeau. Le critère 8 du ticket d5ffeb33 demande des clés
    détruites et « pas seulement marquées inactives » : une colonne `revoked` laisserait
    la clé en base, à portée du premier code qui oublierait de la filtrer — et un filtre
    oublié ne se voit pas en test.

    Rend l'appariement tel qu'il était JUSTE AVANT, avec son environnement : c'est la
    seule occasion de le lire, et le journal en a besoin pour nommer ce qui a été révoqué.
    Nul si rien n'a été supprimé, ce qui est le cas d'un second clic.
    """
    row = await db.fetchrow(
        "DELETE FROM environment_peer WHERE base_url = $1"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label",
        base_url,
    )
    return None if row is None else _peer(row)


async def db_record_revocation(
    db: PairingDb, base_url: str, public_key_fingerprint: str, now: datetime
) -> None:
    """Pose la pierre tombale : de quoi NOMMER le refus au journal, et rien de plus.

    `ON CONFLICT DO UPDATE` parce qu'une origine peut être révoquée, réappariée, puis
    révoquée de nouveau. La dernière révocation est celle qui compte pour le diagnostic ;
    l'historique complet est dans les events, qui ne s'écrasent pas.
    """
    await db.execute(
        "INSERT INTO revoked_pairing (base_url, public_key_fingerprint, revoked_at)"
        " VALUES ($1, $2, $3)"
        " ON CONFLICT (base_url) DO UPDATE SET"
        " public_key_fingerprint = excluded.public_key_fingerprint,"
        " revoked_at = excluded.revoked_at",
        base_url,
        public_key_fingerprint,
        now,
    )


async def db_get_revocation(db: PairingDb, base_url: str) -> datetime | None:
    """La date de révocation de cette origine, s'il y en a une. Lue sur le CHEMIN DE REFUS.

    Appelée seulement quand aucun appariement n'a été trouvé : le chemin nominal ne paie
    pas cette requête. Ce qu'elle rend ne change aucune réponse HTTP — uniquement le mot
    porté au journal.
    """
    row = await db.fetchrow("SELECT revoked_at FROM revoked_pairing WHERE base_url = $1", base_url)
    return None if row is None else row["revoked_at"]


async def db_forget_revocation(db: PairingDb, base_url: str) -> None:
    """Retire la pierre tombale d'une origine qui vient d'être RÉAPPARIÉE.

    Sans cela, une origine révoquée puis réappariée garderait une tombe qui ne décrit plus
    rien — et le jour où elle serait révoquée une seconde fois, la date lue serait celle
    de la première. L'historique, lui, reste entier dans les events : c'est leur rôle, pas
    celui d'une table d'état.
    """
    await db.execute("DELETE FROM revoked_pairing WHERE base_url = $1", base_url)
