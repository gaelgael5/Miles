from __future__ import annotations

from datetime import datetime
from typing import Any

from miles_socle.pairing.store import PeerDb
from miles_socle.signing.identity_model import SINGLETON

from environnement.identity.model import AssignedEnvironment

# Ce que ce module mémorise EN PLUS d'un pair. Le pair lui-même, sa demande en cours et
# son avis de révocation sont lus et écrits par le socle (`miles_socle.pairing.store`),
# qui sert les deux demandeurs ; la TABLE reste déclarée par la migration de ce produit.
#
# POURQUOI UNE TABLE À PART, ET PLUS TROIS COLONNES DE `enrolment_peer`. Les colonnes y
# étaient jusqu'au 29/10/2026, et l'upsert du pair devait alors connaître l'environnement
# assigné pour l'oublier quand l'identité du pair changeait — une requête du socle aurait
# donc porté le nom de colonnes qui n'existent que dans un produit. Rangée sous l'ORIGINE
# du pair qui l'a dite, la mémoire cesse de s'appliquer d'elle-même dès que cette origine
# change : la lecture ne la trouve plus, et personne n'a rien à effacer. L'invariant est
# devenu une jointure au lieu d'être une clause à ne pas oublier.
#
# Conséquence voulue : une stack qui revient chez un enrôlement qu'elle avait quitté
# retrouve ce que CELUI-LÀ lui avait dit, non frais et daté de l'époque. C'est vrai, et la
# date le dit — là où un effacement aurait prétendu qu'on n'avait jamais rien su.


def _environnement(row: Any) -> AssignedEnvironment:
    return AssignedEnvironment(row["slug"], row["label"], row["fetched_at"])


async def db_get_assigned_environment(db: PeerDb, /) -> AssignedEnvironment | None:
    """La dernière valeur connue DU PAIR COURANT, avec sa date. Nulle si on n'a jamais su.

    La jointure n'est pas une commodité : c'est elle qui porte l'invariant. Une valeur
    rangée sous une autre origine a été dite par un autre module d'enrôlement, qui n'a
    jamais rien dit de notre appariement d'aujourd'hui — l'afficher comme repli serait un
    mensonge que la date ne rattraperait pas.

    Nulle AUSSI quand aucun pair n'est enregistré, et c'est la même réponse pour une
    raison différente : l'appelant a lu le pair avant, et sait distinguer les deux.
    """
    row = await db.fetchrow(
        "SELECT a.slug, a.label, a.fetched_at FROM assigned_environment a"
        " JOIN enrolment_peer p ON p.base_url = a.base_url WHERE p.id = $1",
        SINGLETON,
    )
    return None if row is None else _environnement(row)


async def db_save_assigned_environment(
    db: PeerDb, slug: str, label: str, now: datetime
) -> AssignedEnvironment | None:
    """Mémorise ce que le pair vient de dire. Nul si aucun pair n'est enregistré.

    L'origine n'est pas un paramètre : elle est LUE du pair dans la même requête. La
    passer depuis l'appelant ouvrirait la possibilité de ranger sous une origine ce qu'une
    autre a dit, et c'est précisément l'erreur que cette table rend inexprimable.

    Rend ce qui a été ÉCRIT plutôt que ce qu'on voulait écrire : un stockage normalise ce
    qu'on lui donne, et c'est la valeur relue que l'écran affichera.
    """
    row = await db.fetchrow(
        "INSERT INTO assigned_environment (base_url, slug, label, fetched_at)"
        " SELECT p.base_url, $2, $3, $4 FROM enrolment_peer p WHERE p.id = $1"
        " ON CONFLICT (base_url) DO UPDATE SET slug = excluded.slug,"
        " label = excluded.label, fetched_at = excluded.fetched_at"
        " RETURNING slug, label, fetched_at",
        SINGLETON,
        slug,
        label,
        now,
    )
    return None if row is None else _environnement(row)


async def db_clear_assigned_environment(db: PeerDb, /) -> None:
    """Oublie la valeur mémorisée parce que le pair vient de dire qu'il n'en a plus.

    Une valeur mémorisée ne survit PAS à une réponse fraîche qui la contredit (critère 5
    du ticket 2edf1f3c) : la garder ferait afficher un environnement dont l'autorité vient
    de dire qu'il n'est plus le nôtre, et la date n'y changerait rien — elle dirait
    seulement depuis quand on se trompe.

    Seule la ligne DU PAIR COURANT est retirée. Ce qu'un autre enrôlement avait dit ne le
    concerne pas, et ne sera de toute façon jamais relu tant qu'il n'est pas le pair.
    """
    await db.execute(
        "DELETE FROM assigned_environment WHERE base_url ="
        " (SELECT p.base_url FROM enrolment_peer p WHERE p.id = $1)",
        SINGLETON,
    )
