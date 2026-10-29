from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from miles_socle.signing.identity_model import SINGLETON
from miles_socle.signing.keys import ALGORITHM

from environnement.identity.model import AssignedEnvironment, EnrolmentPeer, PairingAttempt

# `module_identity` est lue et écrite par le socle (`miles_socle.signing.identity_store`) :
# la table est déclarée par la migration de CE produit, les requêtes sont au socle, qui
# les sert aux trois. Ne reste ici que ce qui n'appartient qu'à l'environnement — son pair.


class PeerDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


async def db_get_peer(db: PeerDb, /) -> EnrolmentPeer | None:
    row = await db.fetchrow(
        "SELECT base_url, public_key, algorithm, created_at, updated_at,"
        " declared_name, contact_url, revoked_at FROM enrolment_peer WHERE id = $1",
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
        row["declared_name"],
        row["revoked_at"],
        row["contact_url"],
    )


async def db_upsert_peer(
    db: PeerDb,
    base_url: str,
    public_key: str,
    now: datetime,
    declared_name: str | None,
    contact_url: str,
) -> EnrolmentPeer:
    """Enregistre le pair, ou REMPLACE celui qui existe — jamais un second.

    Le remplacement est le ré-appariement : il ne doit pas laisser deux identités pour une
    stack. `created_at` est conservé, parce qu'il date l'appariement initial, qui reste un
    fait même après rotation des clés.

    `revoked_at` est REMISE À NUL : une stack qui vient de se réapparier n'est plus
    révoquée, et laisser la date ferait dire « révoqué » d'un appariement vivant.

    `contact_url` est TOUJOURS réécrite, à la différence du nom déclaré : c'est l'adresse
    qu'on vient de composer avec succès, et c'est par le ré-appariement qu'on la change.
    La conserver au conflit rendrait un repointage inexprimable.

    `declared_name` nul CONSERVE celui qui est en place, au lieu de l'effacer. Ce champ dit
    sous quel nom NOTRE module est connu à l'autre bout : repointer l'adresse du pair à la
    main ne change rien à cela. Mesuré le 28/10/2026 en repointant le transport sur machine
    de test — le nom déclaré disparaissait sans que rien ne le dise, et l'écran de l'autre
    bout continuait pourtant de l'afficher. Une perte silencieuse est pire qu'un refus.

    L'ENVIRONNEMENT RATTACHÉ mémorisé n'est effacé que si l'IDENTITÉ du pair change. Une
    stack qui tourne ses clés chez le même enrôlement garde son repli daté, qui reste vrai
    ; un pair différent, lui, n'a jamais rien dit de nous, et montrer comme repli ce qu'un
    autre module avait décidé serait un mensonge que la date ne rattraperait pas. C'est
    l'inverse de `revoked_at`, effacée dans tous les cas : une date de révocation sur un
    appariement vivant se CONTREDIT, alors qu'un rattachement périmé est seulement vieux —
    et il le dit.
    """
    row = await db.fetchrow(
        "INSERT INTO enrolment_peer (id, base_url, public_key, algorithm, created_at,"
        " updated_at, declared_name, contact_url) VALUES ($1, $2, $3, $4, $5, $5, $6, $7)"
        " ON CONFLICT (id) DO UPDATE SET base_url = excluded.base_url,"
        " public_key = excluded.public_key, algorithm = excluded.algorithm,"
        " updated_at = excluded.updated_at,"
        " declared_name = coalesce(excluded.declared_name, enrolment_peer.declared_name),"
        " contact_url = excluded.contact_url, revoked_at = NULL,"
        " environment_slug = CASE WHEN enrolment_peer.base_url = excluded.base_url"
        " THEN enrolment_peer.environment_slug END,"
        " environment_label = CASE WHEN enrolment_peer.base_url = excluded.base_url"
        " THEN enrolment_peer.environment_label END,"
        " environment_fetched_at = CASE WHEN enrolment_peer.base_url = excluded.base_url"
        " THEN enrolment_peer.environment_fetched_at END"
        " RETURNING base_url, public_key, algorithm, created_at, updated_at,"
        " declared_name, contact_url, revoked_at",
        SINGLETON,
        base_url,
        public_key,
        ALGORITHM,
        now,
        declared_name,
        contact_url,
    )
    return EnrolmentPeer(
        row["base_url"],
        row["public_key"],
        row["algorithm"],
        row["created_at"],
        row["updated_at"],
        row["declared_name"],
        row["revoked_at"],
        row["contact_url"],
    )


def _attempt(row: Any) -> PairingAttempt:
    return PairingAttempt(row["base_url"], row["created_at"], row["name"], row["expires_at"])


async def db_get_attempt(db: PeerDb, /) -> PairingAttempt | None:
    row = await db.fetchrow(
        "SELECT base_url, created_at, name, expires_at FROM pairing_attempt WHERE id = $1",
        SINGLETON,
    )
    return None if row is None else _attempt(row)


async def db_upsert_attempt(
    db: PeerDb, base_url: str, now: datetime, name: str, expires_at: datetime | None
) -> PairingAttempt:
    """Ouvre la tentative, ou REMPLACE celle qui traînait.

    Frapper ailleurs abandonne la demande précédente : garder les deux laisserait l'humain
    coller un code sans savoir chez qui il part, et une seule des deux peut aboutir de
    toute façon — un environnement n'a qu'un module d'enrôlement.
    """
    row = await db.fetchrow(
        "INSERT INTO pairing_attempt (id, base_url, created_at, name, expires_at)"
        " VALUES ($1, $2, $3, $4, $5)"
        " ON CONFLICT (id) DO UPDATE SET base_url = excluded.base_url,"
        " created_at = excluded.created_at, name = excluded.name,"
        " expires_at = excluded.expires_at"
        " RETURNING base_url, created_at, name, expires_at",
        SINGLETON,
        base_url,
        now,
        name,
        expires_at,
    )
    return _attempt(row)


async def db_delete_attempt(db: PeerDb, /) -> bool:
    """Referme la tentative. Rend faux s'il n'y en avait pas."""
    return await db.execute("DELETE FROM pairing_attempt WHERE id = $1", SINGLETON) != "DELETE 0"


async def db_mark_peer_revoked(db: PeerDb, now: datetime) -> bool:
    """Retient l'avis de révocation. Rend faux si aucun pair n'est enregistré.

    `revoked_at IS NULL` dans la clause : un second avis ne REDATE pas le premier. Ce qui
    compte est le moment où l'on a appris, et un pair qui réémettrait son avis ne doit pas
    faire glisser cette date sous les yeux de l'administrateur.

    La ligne n'est pas supprimée : l'empreinte de l'ancien appariement est ce qu'on voudra
    comparer après avoir refrappé, et un écran vide se lirait « jamais apparié ».
    """
    retour = await db.execute(
        "UPDATE enrolment_peer SET revoked_at = $2 WHERE id = $1 AND revoked_at IS NULL",
        SINGLETON,
        now,
    )
    return retour != "UPDATE 0"


async def db_clear_peer_revoked(db: PeerDb, /) -> None:
    """Oublie un avis de révocation que les faits démentent.

    Appelée quand le pair ACCEPTE de nouveau nos appels signés : l'avis n'est qu'un
    indice, et c'est l'appel qui fait foi. Sans cet oubli, un avis arrivé juste avant un
    ré-appariement laisserait l'écran dire « révoqué » d'un appariement vivant — le
    contresens exact que ce ticket corrige, retourné.
    """
    await db.execute("UPDATE enrolment_peer SET revoked_at = NULL WHERE id = $1", SINGLETON)


def _environnement(row: Any) -> AssignedEnvironment | None:
    """Les trois colonnes, ou rien. La base garantit qu'elles ne sont jamais à moitié là.

    Lire `slug` seul suffirait aujourd'hui, mais la lecture dit ce que l'invariant promet :
    le jour où la contrainte sauterait, c'est ici que ça se verrait plutôt qu'à l'affichage.
    """
    if row["environment_slug"] is None or row["environment_fetched_at"] is None:
        return None
    return AssignedEnvironment(
        row["environment_slug"], row["environment_label"], row["environment_fetched_at"]
    )


async def db_get_assigned_environment(db: PeerDb, /) -> AssignedEnvironment | None:
    """La dernière valeur connue, avec sa date. Nulle tant qu'on n'a jamais réussi à la lire.

    Nulle AUSSI quand aucun pair n'est enregistré, et c'est la même réponse pour une
    raison différente : l'appelant a lu le pair avant, et sait distinguer les deux.
    """
    row = await db.fetchrow(
        "SELECT environment_slug, environment_label, environment_fetched_at"
        " FROM enrolment_peer WHERE id = $1",
        SINGLETON,
    )
    return None if row is None else _environnement(row)


async def db_save_assigned_environment(
    db: PeerDb, slug: str, label: str, now: datetime
) -> AssignedEnvironment | None:
    """Mémorise ce que le pair vient de dire. Nul si aucun pair n'est enregistré.

    Rend ce qui a été ÉCRIT plutôt que ce qu'on voulait écrire : un stockage normalise ce
    qu'on lui donne, et c'est la valeur relue que l'écran affichera.
    """
    row = await db.fetchrow(
        "UPDATE enrolment_peer SET environment_slug = $2, environment_label = $3,"
        " environment_fetched_at = $4 WHERE id = $1"
        " RETURNING environment_slug, environment_label, environment_fetched_at",
        SINGLETON,
        slug,
        label,
        now,
    )
    return None if row is None else _environnement(row)


async def db_clear_assigned_environment(db: PeerDb, /) -> None:
    """Oublie la valeur mémorisée parce que le pair vient de dire qu'il n'en a plus.

    Une valeur mémorisée ne survit PAS à une réponse fraîche qui la contredit (critère 5) :
    la garder ferait afficher un environnement dont l'autorité vient de dire qu'il n'est
    plus le nôtre, et la date n'y changerait rien — elle dirait seulement depuis quand on
    se trompe.
    """
    await db.execute(
        "UPDATE enrolment_peer SET environment_slug = NULL, environment_label = NULL,"
        " environment_fetched_at = NULL WHERE id = $1",
        SINGLETON,
    )
