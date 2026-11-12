"""Lire les versions d'un workspace hébergé, et en ordonner une à l'environnement.

Ce module LIT git lui-même, avec le credential que le module de paramétrage lui a confié.
C'est le choix de Gael du 01/11/2026, et sa raison est celle qui avait déjà décidé le sens
du confiage : demander la liste au module de paramétrage ferait dépendre toute lecture de
git de sa disponibilité, et un paramétrage éteint rendrait impossible le choix d'une
version déjà publiée.

L'ordre est poussé HORS de la transaction qui l'enregistre. Un appel réseau dans une
transaction la tient ouverte le temps d'un pair lent, et son échec annulerait un choix que
l'humain a pourtant fait — alors que ce choix est NOTRE état, et qu'il reste vrai même si
le pair ne répond pas. La réponse est écrite ensuite, dans sa propre transaction, avec sa
date : c'est un instantané, pas une vérité courante.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg
import httpx
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventChecker, NewEvent, ObjectRef
from miles_socle.git.access import GitAccess
from miles_socle.git.failures import GitAccessError
from miles_socle.git.forge import Repository, RepositoryUrlError, parse_repository
from miles_socle.git.versions import SavedVersion, fetch_versions
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.model import SecretUndecipherableError
from miles_socle.signing.identity import ModuleIdentityService

from enrolement.environments.model import (
    ENVIRONMENT_OBJECT_KIND,
    Environment,
    EnvironmentNotFoundError,
)
from enrolement.environments.store import db_get_environment
from enrolement.hosting.gitcache import GitCommand, HostingCache
from enrolement.hosting.model import (
    REFUSAL_NO_PEER,
    VERSION_ORDERED_EVENT,
    VERSION_REFUSED_EVENT,
    VERSION_SERVED_EVENT,
    HostedVersion,
    NoRepositoryError,
    NoWorkspaceHostedError,
    RepositoryUnreadableError,
    VersionUnknownError,
    WorkspaceNotConfidedError,
    validate_number,
)
from enrolement.hosting.order import OrderOutcome, push_order
from enrolement.hosting.store import (
    db_get_hosted_version,
    db_git_source,
    db_list_hosted_versions,
    db_order_version,
    db_record_ack,
)
from enrolement.pairing.store_confided_git import credential_aad, db_get_sealed
from enrolement.pairing.store_peers import db_get_peer, db_get_peer_base_url_by_environment

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HostingTarget:
    """De quoi lire git pour un environnement : son workspace, son dépôt, son credential.

    Les quatre résolus ensemble parce qu'aucun des gestes de ce service n'en emploie moins :
    lire les versions comme servir un bundle demandent le dépôt ET le moyen d'y accéder.
    """

    environment: Environment
    workspace_id: str
    repo: Repository
    access: GitAccess


@dataclass(frozen=True)
class HostingService:
    """La version du workspace qu'un environnement sert (story 3bbd4f87)."""

    pool: asyncpg.Pool
    cipher: SecretCipher
    catalog: EventChecker
    now: Callable[[], datetime]
    module: ModuleIdentityService
    http: httpx.AsyncClient
    origin: str | None
    cache: HostingCache
    # Vides en production. Ils ne sont PAS un confort de test : sans eux, aucune
    # campagne ne pourrait éprouver ce service contre un vrai dépôt git, et tout ce
    # qui est ici ne serait vérifié que par des doublures.
    git_test_hosts: tuple[str, ...] = ()

    async def resolve_hosted_versions(self) -> dict[UUID, HostedVersion]:
        """Ce qui est ordonné à chaque environnement, pour la liste de l'écran."""
        return await db_list_hosted_versions(self.pool)

    async def resolve_ordered_version(self, environment_id: UUID) -> HostedVersion | None:
        """Ce qui est ordonné à cet environnement. Aucune lecture de git : rien à récupérer.

        Séparée de la liste des versions, et c'est volontaire : l'écran doit pouvoir dire
        « version 7 ordonnée » même quand la forge est injoignable, puisque ce choix est
        notre état et pas le sien.
        """
        return await db_get_hosted_version(self.pool, environment_id)

    async def resolve_versions(self, environment_id: UUID) -> list[SavedVersion]:
        """Les versions publiées du workspace que cet environnement héberge.

        Récupération COMPLÈTE et non superficielle : le même miroir sert à servir le
        bundle, et un bundle issu d'un dépôt superficiel ne s'ouvre pas (mesuré le
        01/11/2026). Un dépôt récupéré une fois superficiellement resterait marqué tel
        quel, donc le choix se fait dès la première récupération.
        """
        cible = await self.resolve_target(environment_id)
        async with self.cache.opened(cible.workspace_id, cible.access) as git:
            return await self.read_versions(git, cible)

    async def resolve_order_version(
        self, author: EventAuthor, environment_id: UUID, number: int
    ) -> tuple[HostedVersion, OrderOutcome]:
        """Ordonne à l'environnement de servir cette version, et rend ce qu'il en a fait.

        **Le commit n'est jamais une saisie.** L'humain choisit un NUMÉRO ; le commit est
        lu dans le dépôt, ici. Accepter un commit venu de l'écran reviendrait à laisser
        désigner un contenu arbitraire du dépôt — y compris un commit qui n'est la version
        de personne — et c'est précisément ce commit qui autorise ensuite le relais.
        """
        number = validate_number(number)
        cible = await self.resolve_target(environment_id)
        async with self.cache.opened(cible.workspace_id, cible.access) as git:
            versions = await self.read_versions(git, cible)
        choisie = next((v for v in versions if v.number == number), None)
        if choisie is None:
            # La version a pu disparaître à la source entre l'affichage et le clic : c'est
            # une course normale, et elle se dit — pas une saisie à corriger.
            raise VersionUnknownError(number)
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await db_order_version(conn, environment_id, number, choisie.commit, maintenant)
            await self._write_event(
                conn,
                VERSION_ORDERED_EVENT,
                environment_id,
                {
                    "workspace_id": cible.workspace_id,
                    "number": number,
                    "commit": choisie.commit,
                    # Le libellé est au journal et PAS au contrat : ici il date le choix
                    # tel qu'il a été lu, et c'est ce qu'on voudra relire dans un an.
                    "label": choisie.label,
                },
                author,
            )
        log.info(
            "version_ordonnee",
            environment_id=str(environment_id),
            workspace_id=cible.workspace_id,
            number=number,
            commit=choisie.commit,
        )
        issue = await self._push(author, cible, number, choisie.commit)
        hebergee = await db_get_hosted_version(self.pool, environment_id)
        if hebergee is None:  # pragma: no cover - supprimé pendant l'ordre
            raise EnvironmentNotFoundError(f"aucun environnement sous {environment_id}")
        return hebergee, issue

    async def resolve_resend_order(
        self, author: EventAuthor, environment_id: UUID
    ) -> tuple[HostedVersion, OrderOutcome]:
        """Repousse l'ordre déjà enregistré, sans le changer.

        C'est le geste de réparation, et il est explicite : un environnement qui a
        redémarré ou perdu son disque ne sait pas qu'une version lui est ordonnée — il
        n'a aucun moyen de l'apprendre seul, c'est le sens choisi pour ces deux routes.
        """
        cible = await self.resolve_target(environment_id)
        hebergee = await db_get_hosted_version(self.pool, environment_id)
        if hebergee is None:
            raise VersionUnknownError(0)
        issue = await self._push(author, cible, hebergee.number, hebergee.commit)
        apres = await db_get_hosted_version(self.pool, environment_id)
        return (apres or hebergee), issue

    async def resolve_target(self, environment_id: UUID) -> HostingTarget:
        """Résout tout ce qu'il faut pour lire git, ou refuse en NOMMANT ce qui manque.

        Quatre refus distincts, et ils ne se remplacent pas : pas d'environnement, pas de
        workspace placé, personne ne l'expose, pas de dépôt configuré. Chacun appelle un
        geste différent — et un message unique les ferait tous chercher au même endroit.
        """
        environnement = await db_get_environment(self.pool, environment_id)
        if environnement is None:
            raise EnvironmentNotFoundError(f"aucun environnement sous {environment_id}")
        if environnement.workspace_id is None:
            raise NoWorkspaceHostedError(f"{environnement.slug} n'héberge aucun workspace")
        source = await db_git_source(self.pool, environnement.workspace_id)
        if source is None:
            raise WorkspaceNotConfidedError(
                f"aucune connexion confiée n'expose {environnement.workspace_id}"
            )
        if source.repo_url is None:
            raise NoRepositoryError(f"le dépôt de {environnement.workspace_id} n'est pas configuré")
        try:
            # Validée AVANT d'entrer dans une commande git : cette adresse nous arrive par
            # le réseau, et les règles qui la contraignent sont celles du socle — les mêmes
            # que chez celui qui l'a saisie, écrites une seule fois.
            repo = parse_repository(source.repo_url, self.git_test_hosts)
        except RepositoryUrlError as refus:
            raise NoRepositoryError(f"adresse de dépôt refusée : {refus}") from refus
        scelle = await db_get_sealed(self.pool, source.peer_base_url, source.connection_id)
        if scelle is None:  # pragma: no cover - la ligne et son chiffré naissent ensemble
            raise WorkspaceNotConfidedError("aucun credential pour cette connexion")
        try:
            credential = self.cipher.open(
                credential_aad(source.peer_base_url, source.connection_id), scelle
            )
        except SecretUndecipherableError as illisible:
            # Le chiffré ne s'ouvre plus ICI — clé des secrets changée, ligne altérée. À
            # distinguer d'une panne de forge : le geste à faire est de le faire reconfier
            # depuis le module de paramétrage, pas de chercher du côté du dépôt.
            log.warning(
                "credential_confie_illisible",
                base_url=source.peer_base_url,
                connection=source.connection_id,
            )
            raise RepositoryUnreadableError("credential_illisible") from illisible
        return HostingTarget(
            environnement, environnement.workspace_id, repo, GitAccess(token=credential)
        )

    async def read_versions(self, git: GitCommand, cible: HostingTarget) -> list[SavedVersion]:
        """Les versions du dépôt, avec le refus de git TRADUIT dans celui du produit.

        Publique parce que le relais la réemploie : lui aussi doit récupérer avant de
        servir, et une seconde écriture de la même traduction aurait fini par rendre
        une raison différente pour le même échec de git.
        """
        try:
            return await fetch_versions(git, cible.repo.url, depth=None)
        except GitAccessError as inaccessible:
            raise RepositoryUnreadableError(inaccessible.reason.value) from inaccessible

    async def _push(
        self, author: EventAuthor, cible: HostingTarget, number: int, commit: str
    ) -> OrderOutcome:
        """Pousse l'ordre au pair de cet environnement, et écrit ce qu'il a répondu."""
        base_url = await db_get_peer_base_url_by_environment(self.pool, cible.environment.id)
        pair = None if base_url is None else await db_get_peer(self.pool, base_url)
        if pair is None:
            # Aucune stack appariée : il n'y a personne à qui pousser. Ce n'est pas une
            # panne — un environnement déclaré et pas encore apparié est l'état normal du
            # premier jour — et le choix de version reste enregistré, prêt à être poussé.
            return await self._ack(author, cible, None, REFUSAL_NO_PEER)
        issue = await push_order(
            self.http,
            self.module,
            origin=self.origin,
            contact_url=pair.contact_url,
            workspace_id=cible.workspace_id,
            number=number,
            commit=commit,
        )
        return await self._ack(author, cible, issue.served_commit, issue.refusal)

    async def _ack(
        self, author: EventAuthor, cible: HostingTarget, served: str | None, refusal: str | None
    ) -> OrderOutcome:
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await db_record_ack(conn, cible.environment.id, served, refusal, maintenant)
            await self._write_event(
                conn,
                VERSION_SERVED_EVENT if served is not None else VERSION_REFUSED_EVENT,
                cible.environment.id,
                {"workspace_id": cible.workspace_id, "commit": served, "refusal": refusal},
                author,
            )
        return OrderOutcome(served, refusal)

    async def _write_event(
        self,
        conn: Any,
        event_type: str,
        environment_id: UUID,
        properties: dict[str, Any],
        author: EventAuthor,
    ) -> None:
        """Écrit dans la transaction de la modification : pas de modification sans trace."""
        event = NewEvent(
            event_type,
            (ObjectRef(ENVIRONMENT_OBJECT_KIND, str(environment_id)),),
            author,
            properties,
        )
        await db_write_event(conn, event, self.catalog, self.now)
