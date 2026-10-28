from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from enrolement.environments.model import (
    ENVIRONMENT_CREATED_EVENT,
    ENVIRONMENT_DELETED_EVENT,
    ENVIRONMENT_OBJECT_KIND,
    ENVIRONMENT_RENAMED_EVENT,
    Environment,
    EnvironmentDesignatedError,
    EnvironmentNotFoundError,
    EnvironmentPairedError,
    EnvironmentSlugTakenError,
    validate_label,
    validate_slug,
)
from enrolement.environments.store import (
    db_delete_environment,
    db_get_environment,
    db_insert_environment,
    db_list_environments,
    db_update_environment,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class EnvironmentService:
    """Le référentiel des environnements du module d'enrôlement (ticket 2ea50d40).

    Un environnement y porte un libellé — ce qui se lit — et un slug — ce qui s'écrit.
    Les deux restent renommables : rien de durable ne désigne un environnement par son
    slug, l'adresse d'enrôlement le désignant par un identifiant opaque et régénérable.
    Ce qui en découle et qui tient tout ce service : **l'unicité se revérifie à chaque
    renommage**, exactement comme à la création.

    Ce service ne DÉRIVE aucun slug depuis un libellé. La dérivation pré-remplit un champ
    que l'utilisateur garde le droit de changer : c'est une aide à la saisie, et elle vit
    là où la saisie a lieu. Ici n'arrive qu'un choix, qu'on valide sans jamais le réécrire.
    """

    pool: asyncpg.Pool
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_environments(self) -> list[Environment]:
        return await db_list_environments(self.pool)

    async def resolve_create(self, author: EventAuthor, label: str, slug: str) -> Environment:
        """Déclare un environnement : la base tient l'unicité, aucune lecture ne la précède."""
        label, slug = validate_label(label), validate_slug(slug)
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                environnement = await db_insert_environment(conn, uuid4(), slug, label, self.now())
                await self._write_event(
                    conn,
                    ENVIRONMENT_CREATED_EVENT,
                    environnement,
                    {"slug": slug, "label": label},
                    author,
                )
        except asyncpg.UniqueViolationError as exc:
            # La seule contrainte d'unicité de la table. La traduire ici plutôt que de
            # lire avant d'écrire est ce qui rend deux créations concurrentes du même slug
            # inoffensives : une passe, l'autre reçoit ce refus.
            raise EnvironmentSlugTakenError(slug) from exc
        log.info("environnement_declare", environment_id=str(environnement.id), slug=slug)
        return environnement

    async def resolve_rename(
        self, author: EventAuthor, environment_id: UUID, label: str, slug: str
    ) -> Environment:
        """Renomme le libellé, le slug, ou les deux — même unicité qu'à la création."""
        label, slug = validate_label(label), validate_slug(slug)
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                avant = await db_get_environment(conn, environment_id)
                apres = (
                    None
                    if avant is None
                    else await db_update_environment(conn, environment_id, slug, label, self.now())
                )
                if avant is None or apres is None:
                    raise EnvironmentNotFoundError(f"aucun environnement sous {environment_id}")
                await self._write_event(
                    conn,
                    ENVIRONMENT_RENAMED_EVENT,
                    apres,
                    # Les valeurs précédentes sont dans l'event, et c'est tout l'intérêt :
                    # un journal qui ne dit pas ce qu'il y avait avant ne permet pas de
                    # retrouver ce qu'une procédure désignait la semaine dernière.
                    {
                        "slug": slug,
                        "label": label,
                        "previous_slug": avant.slug,
                        "previous_label": avant.label,
                    },
                    author,
                )
                return apres
        except asyncpg.UniqueViolationError as exc:
            raise EnvironmentSlugTakenError(slug) from exc

    async def resolve_delete(self, author: EventAuthor, environment_id: UUID) -> None:
        """Supprime un environnement que rien ne retient.

        Un environnement APPARIÉ ne se supprime pas : on révoque d'abord. Deux gestes qui
        n'ont pas les mêmes conséquences ne s'enchaînent pas tout seuls — supprimer
        emporterait l'appariement, et les devices avec lui, sans que personne l'ait voulu.

        Ce que cette garde ne couvre PAS encore : les devices affectés. Le référentiel des
        devices n'existe pas (tickets de dispatch), et compter zéro serait mentir. Le jour
        où il existe, le refus se dédouble — « révoquez d'abord » et « il reste des
        devices » appellent deux gestes différents, et un message unique les confondrait.
        """
        try:
            async with self.pool.acquire() as conn, conn.transaction():
                environnement = await db_get_environment(conn, environment_id)
                if environnement is None:
                    raise EnvironmentNotFoundError(f"aucun environnement sous {environment_id}")
                # MESURÉ le 28/10/2026 : retirer cette lecture ne fait rougir aucun
                # test — la clé étrangère `ON DELETE RESTRICT` tient seule, et le refus
                # remonte par l'exception rattrapée plus bas. Elle reste parce qu'elle
                # refuse AVANT d'ouvrir une écriture, là où l'autre voie laisse la
                # transaction avorter. Ne pas la croire porteuse de la garde : la garde
                # est dans la migration.
                if environnement.paired_base_url is not None:
                    raise EnvironmentPairedError(
                        f"{environnement.slug} porte l'appariement de"
                        f" {environnement.paired_base_url}"
                    )
                # Une demande EN ATTENTE le désigne (ticket bf2115cd). Elle ne le consomme
                # pas — refusée ou expirée, elle le libère — mais l'effacer sous le pied
                # de l'humain qui vient de le choisir ferait cesser son code d'être
                # révélable sans qu'aucun écran ne dise pourquoi. Plusieurs demandes
                # peuvent le viser ; en nommer une suffit à désigner le geste à faire.
                if environnement.designated_base_url is not None:
                    raise EnvironmentDesignatedError(
                        f"{environnement.slug} est désigné par la demande de"
                        f" {environnement.designated_base_url}"
                    )
                if not await db_delete_environment(conn, environment_id):
                    raise EnvironmentNotFoundError(f"aucun environnement sous {environment_id}")
                await self._write_event(
                    conn,
                    ENVIRONMENT_DELETED_EVENT,
                    environnement,
                    {"slug": environnement.slug, "label": environnement.label},
                    author,
                )
        except asyncpg.ForeignKeyViolationError as exc:
            # La lecture ci-dessus a vu l'environnement libre, et un appariement ou une
            # demande s'y est rattaché avant la suppression. C'est la base qui a le
            # dernier mot. Elle ne dit PAS lequel des deux : les deux clés étrangères
            # portent des noms engendrés, sur lesquels on ne s'appuie pas. Dans cette
            # course — et elle seule — le refus est donc le plus général des deux ; le cas
            # ordinaire passe par les lectures ci-dessus, qui le nomment précisément.
            raise EnvironmentPairedError(f"{environment_id} est encore référencé") from exc
        log.info("environnement_supprime", environment_id=str(environment_id))

    async def _write_event(
        self,
        conn: Any,
        event_type: str,
        environnement: Environment,
        properties: Mapping[str, Any],
        author: EventAuthor,
    ) -> None:
        """Écrit dans la transaction de la modification : pas de modification sans trace."""
        event = NewEvent(
            event_type,
            (ObjectRef(ENVIRONMENT_OBJECT_KIND, str(environnement.id)),),
            author,
            dict(properties),
        )
        await db_write_event(conn, event, self.catalog, self.now)
