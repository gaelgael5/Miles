from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import asyncpg
import httpx
import structlog

from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles_socle.oidc.model import (
    CULTURE_RE,
    LABEL_CULTURE,
    OIDC_SECRET_TYPE,
    Connector,
    ConnectorInput,
    ConnectorInputError,
    ConnectorInUseError,
    ConnectorNotFoundError,
    OidcError,
    validate_connector_id,
    validate_input,
)
from miles_socle.oidc.provider import (
    Identity,
    InvalidTokenError,
    ProviderRefusedError,
    ProviderUnreachableError,
    authorization_url,
    exchange_code,
    fetch_jwks,
    fetch_metadata,
    identity_from_claims,
    new_login_attempt,
    state_digest,
    verify_id_token,
)
from miles_socle.oidc.store import (
    db_count_identities,
    db_delete_connector,
    db_get_connector,
    db_inactive_cultures,
    db_insert_attempt,
    db_insert_connector,
    db_list_connectors,
    db_list_public_connectors,
    db_record_identity,
    db_take_attempt,
    db_update_connector,
)
from miles_socle.secrets.model import Consumer, SecretError
from miles_socle.secrets.service import SecretsService, resolve_attach_secret, resolve_detach_secret

log = structlog.get_logger(__name__)

CREATED_EVENT = "oidc.connector.created"
UPDATED_EVENT = "oidc.connector.updated"
DELETED_EVENT = "oidc.connector.deleted"
ADMIN_RECOGNIZED_EVENT = "oidc.admin_recognized"
EVENT_TYPES = frozenset({CREATED_EVENT, UPDATED_EVENT, DELETED_EVENT, ADMIN_RECOGNIZED_EVENT})
CALLBACK_PATH = "/api/auth/oidc/callback"
# Le temps de s'authentifier chez le fournisseur ; au-delà, la tentative est perdue.
ATTEMPT_TTL = timedelta(minutes=10)
_CONSUMER_KIND = "oidc.connector"


class IssuerUnreachableError(ConnectorInputError):
    """L'émetteur déclaré ne répond pas comme un fournisseur OIDC : rien n'est enregistré."""

    def __init__(self) -> None:
        super().__init__("issuer")


class LoginError(OidcError):
    """Connexion refusée. `code` est rendu à l'écran ; `reason` ne va qu'au journal."""

    def __init__(self, code: str, connector_id: str | None, reason: str) -> None:
        super().__init__(reason)
        self.code, self.connector_id, self.reason = code, connector_id, reason


@dataclass(frozen=True)
class LoginStart:
    url: str
    state: str


@dataclass(frozen=True)
class LoginSuccess:
    connector_id: str
    identity: Identity
    # Administration racine reconnue par l'e-mail (ticket ad33b114) : propre à la session.
    root_admin: bool = False


@dataclass(frozen=True)
class OidcService:
    pool: asyncpg.Pool
    http: httpx.AsyncClient
    secrets: SecretsService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    public_url: str | None
    allow_http_issuer: bool
    # E-mail du compte d'amorçage, relu à chaque connexion : le .env peut changer.
    admin_email: Callable[[], str | None] = lambda: None

    async def resolve_list(self, only_active: bool) -> list[Connector]:
        return await db_list_connectors(self.pool, only_active)

    async def resolve_get(self, connector_id: str) -> Connector:
        found = await db_get_connector(self.pool, connector_id)
        if found is None:
            raise ConnectorNotFoundError(connector_id)
        return found

    async def resolve_create(
        self, author: EventAuthor, connector_id: str, raw: ConnectorInput
    ) -> Connector:
        connector_id = validate_connector_id(connector_id)
        data = validate_input(raw, self.allow_http_issuer)
        await self._check_issuer(data.issuer)
        async with self.pool.acquire() as conn, conn.transaction():
            await self._check_cultures(conn, data)
            await self._attach(conn, data.client_secret_slug, connector_id)
            await db_insert_connector(conn, connector_id, data, self.now())
            await self._event(conn, CREATED_EVENT, connector_id, author, {"issuer": data.issuer})
        log.info("oidc_connecteur_cree", connector=connector_id, issuer=data.issuer)
        return await self.resolve_get(connector_id)

    async def resolve_update(
        self, author: EventAuthor, connector_id: str, raw: ConnectorInput
    ) -> Connector:
        data = validate_input(raw, self.allow_http_issuer)
        current = await self.resolve_get(connector_id)
        if data.issuer != current.issuer:
            await self._check_issuer(data.issuer)
        async with self.pool.acquire() as conn, conn.transaction():
            locked = await db_get_connector(conn, connector_id, lock=True)
            if locked is None:
                raise ConnectorNotFoundError(connector_id)
            await self._check_cultures(conn, data)
            if data.client_secret_slug != locked.client_secret_slug:
                await resolve_detach_secret(
                    conn, locked.client_secret_slug, self._consumer(connector_id)
                )
                await self._attach(conn, data.client_secret_slug, connector_id)
            await db_update_connector(conn, connector_id, data, self.now())
            changes = _changes(locked, data)
            # Avant et après pour chaque champ : les deux cases sont des réglages de
            # sécurité, et le journal doit dire qui les a cochées ou décochées.
            await self._event(conn, UPDATED_EVENT, connector_id, author, {"changes": changes})
        # Les sessions déjà ouvertes ne dépendent pas de la configuration : le changement
        # vaut pour les authentifications suivantes, sans casser celles en cours.
        log.info("oidc_connecteur_modifie", connector=connector_id, fields=sorted(changes))
        return await self.resolve_get(connector_id)

    async def resolve_delete(self, author: EventAuthor, connector_id: str) -> None:
        async with self.pool.acquire() as conn, conn.transaction():
            locked = await db_get_connector(conn, connector_id, lock=True)
            if locked is None:
                raise ConnectorNotFoundError(connector_id)
            # Comportement retenu : refus. Supprimer l'annuaire laisserait des comptes
            # orphelins ; on le désactive, ce qui ferme la porte sans rien perdre.
            identities = await db_count_identities(conn, connector_id)
            if identities:
                raise ConnectorInUseError(connector_id, identities)
            await resolve_detach_secret(
                conn, locked.client_secret_slug, self._consumer(connector_id)
            )
            await db_delete_connector(conn, connector_id)
            await self._event(conn, DELETED_EVENT, connector_id, author, {})
        log.info("oidc_connecteur_supprime", connector=connector_id)

    async def resolve_start_login(self, connector_id: str) -> LoginStart:
        redirect_uri = self._redirect_uri(connector_id)
        connector = await db_get_connector(self.pool, connector_id)
        # Un connecteur inactif ne s'ouvre pas, même appelé directement par son adresse.
        if connector is None or not connector.active:
            raise LoginError("connecteur_inconnu", None, "connecteur absent ou inactif")
        metadata = await self._metadata(connector)
        attempt = new_login_attempt()
        now = self.now()
        await db_insert_attempt(
            self.pool,
            state_digest(attempt.state),
            connector.id,
            attempt.nonce,
            attempt.code_verifier,
            now + ATTEMPT_TTL,
            now,
        )
        url = authorization_url(
            metadata, connector.client_id, connector.scopes, redirect_uri, attempt
        )
        return LoginStart(url, attempt.state)

    async def resolve_finish_login(
        self,
        state: str | None,
        browser_state: str | None,
        code: str | None,
        provider_error: str | None,
    ) -> LoginSuccess:
        # Le state revenu doit être celui posé dans CE navigateur : sinon on ouvrirait
        # chez la victime une session obtenue par l'attaquant (connexion forcée).
        if not state or not browser_state or state != browser_state:
            raise LoginError("state_invalide", None, "state absent ou différent du navigateur")
        attempt = await db_take_attempt(self.pool, state_digest(state), self.now())
        if attempt is None:
            raise LoginError("state_invalide", None, "tentative inconnue, expirée ou rejouée")
        connector_id: str = attempt["connector_id"]
        if provider_error is not None or not code:
            raise LoginError("refus_fournisseur", connector_id, "retour du fournisseur sans code")
        connector = await db_get_connector(self.pool, connector_id)
        if connector is None or not connector.active:
            raise LoginError("connecteur_inconnu", connector_id, "connecteur désactivé en cours")
        claims = await self._authenticate(connector, attempt, code)
        identity = identity_from_claims(claims, connector.display_name_claim)
        if connector.groups_claim not in claims:
            # Aucun rôle ne pourra se lire : le journal dit pourquoi, au lieu d'un refus
            # sans cause le jour où les correspondances liront ce claim.
            log.warning(
                "oidc_claim_groupes_absent", connector=connector.id, claim=connector.groups_claim
            )
        root_admin = self._recognizes_admin(connector, identity)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_record_identity(conn, connector.id, identity.subject, self.now())
            if root_admin:
                # Accès à l'administration racine : il doit se retrouver dans le journal.
                author = EventAuthor(connector.id, identity.subject)
                await self._event(
                    conn, ADMIN_RECOGNIZED_EVENT, connector.id, author, {"sub": identity.subject}
                )
        log.info("oidc_connexion_reussie", connector=connector.id, root_admin=root_admin)
        return LoginSuccess(connector.id, identity, root_admin)

    async def resolve_public_list(self, culture: str | None) -> list[tuple[str, str]]:
        # Culture mal formée ou absente : repli sur en-US, sans erreur (critère 5).
        wanted = culture if culture and CULTURE_RE.match(culture) else LABEL_CULTURE
        return await db_list_public_connectors(self.pool, wanted)

    @staticmethod
    async def _check_cultures(conn: Any, data: ConnectorInput) -> None:
        # Seules les cultures actives se saisissent : le référentiel est donné, et son
        # activation est centralisée (ticket des cultures).
        if await db_inactive_cultures(conn, list(data.labels)):
            raise ConnectorInputError("labels")

    def _recognizes_admin(self, connector: Connector, identity: Identity) -> bool:
        """Seule garde de ce chemin vers l'administration racine : la case du connecteur.

        Égalité insensible à la casse et rien d'autre (décision du 19/10/2026) : ni
        espaces retirés, ni domaine comparé. `email_verified` n'est pas exigé, c'est la
        case qui ne se coche que sur un annuaire où l'adresse ne se choisit pas.
        """
        admin_email = self.admin_email()
        if not connector.recognize_admin or not admin_email or not identity.email:
            return False
        return identity.email.lower() == admin_email.lower()

    async def _authenticate(self, connector: Connector, attempt: Any, code: str) -> dict[str, Any]:
        metadata = await self._metadata(connector)
        try:
            secret = await self.secrets.resolve_secret(
                connector.client_secret_slug, OIDC_SECRET_TYPE
            )
        except SecretError as exc:
            raise LoginError("configuration_connecteur", connector.id, str(exc)) from None
        try:
            token = await exchange_code(
                self.http,
                metadata,
                connector.client_id,
                secret,
                code,
                attempt["code_verifier"],
                self._redirect_uri(connector.id),
            )
            jwks = await fetch_jwks(self.http, metadata)
            return verify_id_token(token, jwks, metadata, connector.client_id, attempt["nonce"])
        except ProviderUnreachableError as exc:
            raise LoginError("fournisseur_injoignable", connector.id, str(exc)) from None
        except ProviderRefusedError as exc:
            raise LoginError("refus_fournisseur", connector.id, str(exc)) from None
        except InvalidTokenError as exc:
            raise LoginError("jeton_invalide", connector.id, str(exc)) from None

    async def _metadata(self, connector: Connector) -> Any:
        try:
            return await fetch_metadata(self.http, connector.issuer, self.allow_http_issuer)
        except ProviderUnreachableError as exc:
            raise LoginError("fournisseur_injoignable", connector.id, str(exc)) from None

    async def _check_issuer(self, issuer: str) -> None:
        try:
            await fetch_metadata(self.http, issuer, self.allow_http_issuer)
        except ProviderUnreachableError as exc:
            log.warning("oidc_emetteur_injoignable", issuer=issuer, reason=str(exc))
            raise IssuerUnreachableError from None

    def _redirect_uri(self, connector_id: str) -> str:
        if self.public_url is None:
            raise LoginError("url_publique_absente", connector_id, "MILES_PUBLIC_URL absente")
        return self.public_url + CALLBACK_PATH

    async def _attach(self, conn: Any, slug: str, connector_id: str) -> None:
        try:
            await resolve_attach_secret(conn, slug, OIDC_SECRET_TYPE, self._consumer(connector_id))
        except SecretError:
            raise ConnectorInputError("client_secret_slug") from None

    @staticmethod
    def _consumer(connector_id: str) -> Consumer:
        return Consumer(_CONSUMER_KIND, connector_id)

    async def _event(
        self,
        conn: Any,
        event_type: str,
        connector_id: str,
        author: EventAuthor,
        properties: Mapping[str, Any],
    ) -> None:
        event = NewEvent(
            event_type, (ObjectRef("oidc_connector", connector_id),), author, properties
        )
        await db_write_event(conn, event, self.catalog, self.now)


_TRACKED_FIELDS = (
    "issuer",
    "client_id",
    "client_secret_slug",
    "scopes",
    "active",
    "groups_claim",
    "display_name_claim",
    "recognize_admin",
    "manage_associations",
)


def _changes(before: Connector, after: ConnectorInput) -> dict[str, dict[str, Any]]:
    # Aucun de ces champs n'est secret : le secret client n'apparaît que par son slug.
    changes = {
        name: {"before": getattr(before, name), "after": getattr(after, name)}
        for name in _TRACKED_FIELDS
        if getattr(before, name) != getattr(after, name)
    }
    merged = {**before.labels, **after.labels}
    merged = {culture: label for culture, label in merged.items() if label}
    if merged != dict(before.labels):
        changes["labels"] = {"before": dict(before.labels), "after": merged}
    return changes
