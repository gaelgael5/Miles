"""Le câblage des services du socle sur une application, écrit UNE fois.

Les trois produits posaient les mêmes sept services, dans le même ordre, avec les mêmes
pièges — et le harnais de test les reposait une seconde fois. Quatre copies d'un câblage
dont l'ordre compte : les préférences reçoivent les cultures, et les intervertir ne casse
pas à la construction, seulement à l'exécution.

La PRODUCTION et le HARNAIS DE TEST appellent cette même fonction. C'est ce qui rend
impossible — et non plus seulement improbable — l'oubli d'un service du socle dans le
montage de test, panne que `LESSONS.md` porte deux fois.

Ce qui reste à l'appelant : lire sa configuration, ouvrir son pool, lire son `.env` et sa
clé de secrets AVANT tout le reste (fail closed), construire son catalogue d'events et son
client HTTP — dont il garde la fermeture — puis poser SES propres services.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial
from typing import Protocol

import asyncpg
import httpx
from fastapi import FastAPI

from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.api_preferences import PreferencesService
from miles_socle.auth.context import AuthContext, utc_now
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.cultures.service import CulturesService
from miles_socle.events.model import EventTypeCatalog
from miles_socle.health.probe import resolve_health
from miles_socle.oidc.service import OidcService
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService


class SocleRuntime(Protocol):
    """Ce que le câblage lit dans la configuration, sans savoir d'où elle vient.

    Un Protocol et non `SocleWebSettings` directement : le harnais de test passe un objet
    léger — session courte, cookie non sécurisé pour traverser le transport ASGI, émetteur
    en HTTP admis pour éprouver un fournisseur jetable — et le socle n'a pas besoin de
    pydantic pour câbler.
    """

    @property
    def session_ttl_s(self) -> int: ...

    @property
    def cookie_secure(self) -> bool: ...

    @property
    def public_url(self) -> str | None: ...

    @property
    def allow_http_identity_providers(self) -> bool: ...

    @property
    def db_connect_timeout_s(self) -> float: ...


def wire_socle_services(
    app: FastAPI,
    *,
    settings: SocleRuntime,
    pool: asyncpg.Pool,
    store: AdminAccountStore,
    cipher: SecretCipher,
    catalog: EventTypeCatalog,
    http: httpx.AsyncClient,
    expected_schema_version: int,
    now: Callable[[], datetime] = utc_now,
) -> None:
    """Pose les sept services du socle sur `app.state`. L'ordre n'est pas décoratif.

    `http` est reçu et non construit : le portail le partage avec ses propres services, et
    c'est à l'appelant de le fermer — une fermeture faite ici le refermerait sous les
    services du produit.
    """
    # La version attendue vient des fichiers embarqués dans l'image du produit : c'est ce
    # que son code sait servir, et la base doit l'avoir atteinte.
    app.state.health_probe = partial(
        resolve_health, pool, expected_schema_version, settings.db_connect_timeout_s
    )
    app.state.auth = AuthContext(
        store=store,
        db=pool,
        throttle=LoginThrottle(),
        session_ttl=timedelta(seconds=settings.session_ttl_s),
        cookie_secure=settings.cookie_secure,
    )
    app.state.secrets = SecretsService(pool, cipher, catalog, now)
    app.state.cultures = CulturesService(pool, catalog, now)
    # APRÈS les cultures, et pas avant : les préférences les reçoivent. Les intervertir ne
    # casse pas à la construction, seulement à l'exécution — d'où un seul endroit où
    # l'ordre est écrit.
    app.state.preferences = PreferencesService(pool, app.state.cultures, now)
    app.state.oidc = OidcService(
        pool,
        http,
        app.state.secrets,
        catalog,
        now,
        settings.public_url,
        settings.allow_http_identity_providers,
        # Recalculé à chaque lecture, jamais capturé : après une réinitialisation du compte
        # dans `.env`, l'ancienne adresse ne reconnaît plus personne.
        admin_email=lambda: store.account.email if store.account else None,
    )
    # Lue par les routes qui construisent une URL de retour. Posée ici pour que `None` —
    # une instance sans adresse publique, OIDC indisponible — soit un état explicite.
    app.state.public_url = settings.public_url
