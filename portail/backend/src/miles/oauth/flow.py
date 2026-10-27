from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import asyncpg
import structlog

from miles.apikeys.model import Access
from miles.events.journal import db_write_event
from miles.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef
from miles.oauth.clients import GRANTED_EVENT, OAuthClient, OAuthClientsService
from miles.oauth.model import (
    ACCESS_PREFIX,
    ACCESS_TTL,
    CHALLENGE_RE,
    CODE_PREFIX,
    CODE_TTL,
    REFRESH_PREFIX,
    REFRESH_TTL,
    OAuthError,
    Person,
    digest,
    new_secret,
    pkce_matches,
    same_resource,
)

log = structlog.get_logger(__name__)


class AuthorizeRefused(Exception):
    """Client ou adresse de retour inconnus : on le dit à l'écran, on ne redirige pas.

    Rediriger vers une adresse non déclarée enverrait la réponse à qui l'a fabriquée.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AuthorizeRedirect(Exception):
    """Refus à renvoyer au client, sur son adresse de retour déclarée (RFC 6749 §4.1.2.1)."""

    def __init__(self, url: str) -> None:
        super().__init__(url)
        self.url = url


@dataclass(frozen=True)
class AuthorizeRequest:
    client: OAuthClient
    redirect_uri: str
    code_challenge: str
    state: str | None
    resource: str


@dataclass(frozen=True)
class OAuthFlow:
    """Le parcours OAuth de Miles : autorisation avec consentement, échange, rafraîchissement."""

    pool: asyncpg.Pool
    clients: OAuthClientsService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    # Adresse publique de la surface MCP ; None : MILES_PUBLIC_URL absente, OAuth fermé.
    resource: str | None

    async def resolve_request(self, params: Mapping[str, str]) -> AuthorizeRequest:
        """Valide une demande d'autorisation, dans l'ordre que dicte la sécurité."""
        if self.resource is None:
            raise AuthorizeRefused("oauth_non_configure")
        client = await self.clients.resolve_get(params.get("client_id", ""))
        redirect_uri = params.get("redirect_uri", "")
        if client is None:
            raise AuthorizeRefused("client_inconnu")
        if redirect_uri not in client.redirect_uris:
            raise AuthorizeRefused("adresse_de_retour_inconnue")
        state = params.get("state")
        # À partir d'ici l'adresse de retour est sûre : les refus repartent vers le client.
        if params.get("response_type") != "code":
            raise _redirect(redirect_uri, state, "unsupported_response_type", "code attendu")
        challenge = params.get("code_challenge", "")
        if params.get("code_challenge_method") != "S256" or not CHALLENGE_RE.match(challenge):
            raise _redirect(redirect_uri, state, "invalid_request", "PKCE S256 obligatoire")
        asked = params.get("resource")
        if asked is not None and not same_resource(asked, self.resource):
            raise _redirect(redirect_uri, state, "invalid_target", "ressource inconnue")
        return AuthorizeRequest(client, redirect_uri, challenge, state, self.resource)

    async def resolve_approve(
        self,
        request: AuthorizeRequest,
        person: Person,
        grants: Mapping[str, Access],
        allowed: Mapping[str, Access],
    ) -> str:
        """Rend l'adresse de retour portant le code ; les droits ne dépassent jamais `allowed`."""
        for workspace, access in grants.items():
            ceiling = allowed.get(workspace)
            # Consentir n'accorde que ce qu'on a : jamais l'écriture sur un workspace qu'on
            # ne fait que lire, ni quoi que ce soit sur un workspace hors de ses droits.
            if ceiling is None or (access is Access.WRITE and ceiling is not Access.WRITE):
                raise AuthorizeRefused("droit_excessif")
        code = new_secret(CODE_PREFIX)
        await self.pool.execute(
            "INSERT INTO oauth_codes (digest, client_id, redirect_uri, code_challenge,"
            " person_directory, person_subject, person_kind, person_email, display_name,"
            " grants, resource, expires_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,"
            " $11, $12)",
            digest(code),
            request.client.id,
            request.redirect_uri,
            request.code_challenge,
            person.directory,
            person.subject,
            person.kind,
            person.email,
            person.display_name,
            json.dumps({w: a.value for w, a in sorted(grants.items())}),
            request.resource,
            self.now() + CODE_TTL,
        )
        log.info("oauth_consentement", client=request.client.id, workspaces=len(grants))
        return _with_query(request.redirect_uri, {"code": code, "state": request.state})

    @staticmethod
    def deny(request: AuthorizeRequest) -> str:
        return _with_query(request.redirect_uri, {"error": "access_denied", "state": request.state})

    async def resolve_token(self, form: Mapping[str, str]) -> dict[str, Any]:
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            return await self._exchange(form)
        if grant_type == "refresh_token":
            return await self._refresh(form)
        raise OAuthError("unsupported_grant_type", "authorization_code ou refresh_token")

    async def _exchange(self, form: Mapping[str, str]) -> dict[str, Any]:
        code, verifier = form.get("code", ""), form.get("code_verifier", "")
        # Consommé d'abord, et validé seulement ensuite, hors de la transaction qui suit : un
        # code présenté une fois, même dans un échange refusé, ne sert plus (RFC 6749
        # §10.5). L'UPDATE conditionnel départage deux échanges concurrents du même code.
        row = await self.pool.fetchrow(
            "UPDATE oauth_codes SET used_at = $2 WHERE digest = $1 AND used_at IS NULL RETURNING *",
            digest(code),
            self.now(),
        )
        if (
            row is None
            or row["expires_at"] <= self.now()
            or row["client_id"] != form.get("client_id")
            or row["redirect_uri"] != form.get("redirect_uri")
            or not pkce_matches(verifier, row["code_challenge"])
        ):
            raise OAuthError("invalid_grant", "code inconnu, expiré, déjà utilisé ou mal lié")
        async with self.pool.acquire() as conn, conn.transaction():
            grant_id = uuid.uuid4().hex
            await conn.execute(
                "INSERT INTO oauth_grants (id, client_id, person_directory, person_subject,"
                " person_kind, person_email, display_name, grants, resource, created_at)"
                " VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)",
                grant_id,
                row["client_id"],
                row["person_directory"],
                row["person_subject"],
                row["person_kind"],
                row["person_email"],
                row["display_name"],
                row["grants"],
                row["resource"],
                self.now(),
            )
            author = EventAuthor(row["person_directory"], row["person_subject"])
            ref = ObjectRef("oauth_client", row["client_id"])
            properties = {"grant_id": grant_id, "grants": json.loads(row["grants"])}
            event = NewEvent(GRANTED_EVENT, (ref,), author, properties)
            await db_write_event(conn, event, self.catalog, self.now)
            tokens = await self._issue(conn, grant_id)
        log.info("oauth_autorisation_creee", client=row["client_id"], grant=grant_id)
        return tokens

    async def _refresh(self, form: Mapping[str, str]) -> dict[str, Any]:
        raw = form.get("refresh_token", "")
        async with self.pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT t.grant_id, t.expires_at, t.used_at, g.revoked_at, g.client_id"
                " FROM oauth_tokens t JOIN oauth_grants g ON g.id = t.grant_id"
                " WHERE t.digest = $1 AND t.kind = 'refresh' FOR UPDATE OF t",
                digest(raw),
            )
            if row is None or row["revoked_at"] is not None:
                raise OAuthError("invalid_grant", "jeton de rafraîchissement inconnu ou révoqué")
            replayed = row["used_at"] is not None
            if replayed:
                # Rejeu d'un jeton déjà renouvelé : l'un des deux porteurs l'a volé. On ne
                # sait pas lequel, on coupe l'autorisation entière (RFC 9700 §4.14). Le
                # refus part après la validation de la transaction : levé ici, il annulerait
                # la révocation qu'il annonce.
                await conn.execute(
                    "UPDATE oauth_grants SET revoked_at = $2 WHERE id = $1",
                    row["grant_id"],
                    self.now(),
                )
                log.warning("oauth_rejeu_rafraichissement", grant=row["grant_id"])
            elif row["expires_at"] <= self.now() or row["client_id"] != form.get("client_id"):
                raise OAuthError("invalid_grant", "jeton expiré ou d'un autre client")
            else:
                await conn.execute(
                    "UPDATE oauth_tokens SET used_at = $2 WHERE digest = $1",
                    digest(raw),
                    self.now(),
                )
                return await self._issue(conn, row["grant_id"])
        raise OAuthError("invalid_grant", "jeton déjà utilisé : autorisation révoquée")

    async def _issue(self, conn: Any, grant_id: str) -> dict[str, Any]:
        access, refresh, now = new_secret(ACCESS_PREFIX), new_secret(REFRESH_PREFIX), self.now()
        for raw, kind, ttl in ((access, "access", ACCESS_TTL), (refresh, "refresh", REFRESH_TTL)):
            await conn.execute(
                "INSERT INTO oauth_tokens (digest, grant_id, kind, expires_at, created_at)"
                " VALUES ($1, $2, $3, $4, $5)",
                digest(raw),
                grant_id,
                kind,
                now + ttl,
                now,
            )
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": refresh,
        }


def _redirect(uri: str, state: str | None, error: str, description: str) -> AuthorizeRedirect:
    query = {"error": error, "error_description": description, "state": state}
    return AuthorizeRedirect(_with_query(uri, query))


def _with_query(uri: str, values: Mapping[str, str | None]) -> str:
    query = urlencode({k: v for k, v in values.items() if v is not None})
    return f"{uri}{'&' if '?' in uri else '?'}{query}"
