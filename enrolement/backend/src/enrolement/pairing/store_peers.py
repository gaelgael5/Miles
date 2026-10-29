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
        row["contact_url"],
    )


async def db_upsert_peer(
    db: PairingDb,
    base_url: str,
    public_key: str,
    now: datetime,
    name: str | None,
    environment_id: UUID,
    contact_url: str,
) -> EnvironmentPeer:
    """Enregistre l'environnement apparié, ou REMPLACE sa clé — jamais un doublon.

    Le remplacement est le ré-appariement. `created_at` est conservé : il date
    l'appariement initial, qui reste un fait même après rotation des clés.

    L'environnement, lui, est posé à l'insertion et JAMAIS réécrit au conflit : il vient
    de la demande, qui l'a elle-même hérité de cet appariement s'il en portait un. Le
    rattachement d'un appariement hérité passe par `db_attach_peer_environment`, et c'est
    la seule autre voie — déplacer un appariement conclu d'un environnement vers un autre
    reste inexprimable ici, ce qui vaut mieux qu'une garde qu'on peut oublier d'appeler.

    `contact_url` est posée à l'insertion et, elle aussi, JAMAIS réécrite au conflit —
    l'inverse exact de la règle du module d'environnement, et les deux sont justes. Là-bas
    elle vaut l'adresse qu'on vient de composer avec succès ; ici elle vaut ce que NOTRE
    administrateur a saisi, et une stack qui tourne ses clés n'a aucune raison de l'effacer.
    Elle se change par `db_set_peer_contact_url`, qui est un geste, pas un effet de bord.
    """
    row = await db.fetchrow(
        "INSERT INTO environment_peer (base_url, public_key, algorithm, created_at,"
        " updated_at, name, environment_id, contact_url)"
        " VALUES ($1, $2, $3, $4, $4, $5, $6, $7)"
        " ON CONFLICT (base_url) DO UPDATE SET public_key = excluded.public_key,"
        " algorithm = excluded.algorithm, updated_at = excluded.updated_at,"
        " name = excluded.name"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id, contact_url,"
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
        contact_url,
    )
    return _peer(row)


async def db_get_peer(db: PairingDb, base_url: str) -> EnvironmentPeer | None:
    row = await db.fetchrow(
        "SELECT base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id, contact_url,"
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
        " environment_id, contact_url,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label"
        " FROM environment_peer ORDER BY base_url"
    )
    return [_peer(row) for row in rows]


async def db_count_peer_devices(db: PairingDb, base_url: str) -> int:
    """Le nombre de devices affectés à cet appariement. VAUT ZÉRO PARTOUT AUJOURD'HUI.

    Le référentiel des devices n'existe pas encore : aucune table ne porte l'affectation,
    et il n'y a donc littéralement rien à compter. Cette fonction existe quand même, et
    c'est voulu : elle est LE SEUL endroit à rebrancher le jour où le parc arrive. Une
    garde dispersée en trois endroits se rebranche en deux, et c'est le troisième qui
    laisse passer un déplacement silencieux de devices.

    Rend 0 et jamais nul. `device_count` vaut `null` dans l'API parce qu'on ne sait pas
    compter, et l'écran affiche « — » ; ici il faut un compte — rendre nul au nom de la
    prudence rendrait inutilisable une action qu'on vient d'ouvrir. Les deux ne disent pas
    la même chose et ne se fondent pas : l'une informe un humain, l'autre décide.

    Ni `db` ni `base_url` ne servent encore : ils sont là parce que la vraie requête les
    prendra, et changer la signature le jour du branchement ferait toucher l'appelant.
    """
    return 0


async def db_set_peer_environment(
    db: PairingDb,
    base_url: str,
    environment_id: UUID,
    now: datetime,
    previous_environment_id: UUID | None,
) -> EnvironmentPeer | None:
    """Pose l'environnement d'un appariement CONCLU : rattachement ou déplacement.

    Les deux gestes, une seule écriture, parce que c'est la même : ce qui les distingue est
    ce qu'il y avait avant, et c'est l'appelant qui le sait et qui en tire l'event et les
    gardes. Le déplacement n'est ouvert que tant que l'appariement ne porte aucun device
    (arbitrage du 29/10/2026) ; cette garde est chez l'appelant, pas ici — une écriture ne
    sait pas compter des devices.

    `environment_id IS NOT DISTINCT FROM $4` n'est pas une précaution : c'est ce qui ferme
    la course que la lecture préalable ne voit pas. MESURÉ le 28/10/2026 sur la version qui
    comparait à `NULL` : sans cette clause, deux onglets qui rattachent en même temps
    voient tous deux le champ vide et la seconde écriture ÉCRASE la première — un
    déplacement silencieux. Aucune contrainte d'unicité ne le rattraperait, les deux
    écritures portant sur la MÊME ligne. `IS NOT DISTINCT FROM` et non `=`, pour que le cas
    « il n'y avait rien » se compare comme les autres.

    Rend nul quand rien n'a bougé, sans dire lequel des cas : l'appelant a lu l'appariement
    juste avant et sait le distinguer.
    """
    row = await db.fetchrow(
        "UPDATE environment_peer SET environment_id = $2, updated_at = $3"
        " WHERE base_url = $1 AND environment_id IS NOT DISTINCT FROM $4"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id, contact_url,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label",
        base_url,
        environment_id,
        now,
        previous_environment_id,
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
        " environment_id, contact_url,"
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


async def db_set_peer_contact_url(
    db: PairingDb, base_url: str, contact_url: str
) -> EnvironmentPeer | None:
    """Change l'adresse où l'on JOINT cette stack. Nul si l'appariement n'existe plus.

    Un geste à part, et non un effet de bord d'une autre écriture : c'est la seule chose
    que ce module compose vers l'extérieur, et il doit rester clair qui l'a décidée.
    L'identité, elle, ne se change pas — elle vient de la stack et entre dans ce qu'on
    vérifie d'elle.
    """
    row = await db.fetchrow(
        "UPDATE environment_peer SET contact_url = $2 WHERE base_url = $1"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at, name,"
        " environment_id, contact_url,"
        " (SELECT e.slug FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_slug,"
        " (SELECT e.label FROM environment e WHERE e.id = environment_peer.environment_id)"
        " AS environment_label",
        base_url,
        contact_url,
    )
    return None if row is None else _peer(row)
