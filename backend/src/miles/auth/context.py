from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Request, Response

from miles.auth.admin_store import AdminAccountStore
from miles.auth.sessions import (
    LOCAL_ADMIN_KIND,
    SESSION_COOKIE,
    DbExecutor,
    db_create_session,
    new_session_token,
)
from miles.auth.throttle import LoginThrottle

UNKNOWN_ORIGIN = "inconnue"


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class AuthContext:
    """Ce dont les routes d'authentification ont besoin, posé sur app.state au démarrage."""

    store: AdminAccountStore
    db: DbExecutor
    throttle: LoginThrottle
    session_ttl: timedelta
    cookie_secure: bool
    now: Callable[[], datetime] = utc_now

    async def resolve_open_admin_session(self, response: Response, username: str) -> None:
        token, digest = new_session_token()
        await db_create_session(
            self.db, digest, LOCAL_ADMIN_KIND, username, self.now() + self.session_ttl
        )
        # Pas d'attribut Domain : cookie limité à l'hôte qui l'a posé, jamais
        # partagé avec un service voisin du même domaine. SameSite=Strict tient
        # lieu de protection CSRF, l'IHM et l'API étant sur la même origine.
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=int(self.session_ttl.total_seconds()),
            httponly=True,
            secure=self.cookie_secure,
            samesite="strict",
            path="/",
        )


def auth_context(request: Request) -> AuthContext:
    context: AuthContext = request.app.state.auth
    return context


def client_origin(request: Request) -> str:
    # X-Real-IP est posé par le nginx du frontend, seul à joindre le backend (aucun
    # port publié) : on ne lit pas X-Forwarded-For, que le client peut forger.
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip
    return request.client.host if request.client else UNKNOWN_ORIGIN
