"""Le harnais des gardes de surface : ce que les trois `test_app*.py` partagent.

Extrait le 3 novembre 2026 (enabler `82ec7d76`), quand `test_app.py` a dépassé la limite
de 300 lignes du dépôt. Les gardes de surface GROSSISSENT par construction — chaque route
ajoutée y ajoute sa vérification, et c'est le seul endroit où un chemin ouvert sans sa
garde fait rougir quelque chose. Elles sont donc rangées par NATURE de surface, et ce
fichier porte ce qu'aucune des trois ne peut porter seule.

Ce n'est pas un fichier de test : il ne contient aucune assertion. Les fixtures, elles,
sont dans `conftest.py`, qui est le seul endroit où pytest les cherche sans import.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.events.model import EventTypeCatalog
from miles_socle.health.probe import HealthReport

from environnement.app import build_app
from environnement.event_types import code_event_types
from environnement.identity.service import IdentityService

# Le `nginx.conf` DU PRODUIT : il reste au produit (décision du 28/10/2026), et c'est
# lui qui décide ce qui atteint le backend.
NGINX = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"


def chemins_servis() -> set[str]:
    """Les chemins servis, lus dans la spec OpenAPI.

    Et non dans `app.routes` : cette version de FastAPI y place des enveloppes de
    routeur inclus, sans attribut `path`. La spec est l'interface publique, elle ne
    dépend pas de la forme interne du routeur.
    """
    return set(build_app().openapi()["paths"])


class NoSessionDb:
    """Base dont la table des sessions est vide : aucun jeton présenté n'y existe.

    C'est exactement l'état du produit vis-à-vis d'un cookie ouvert sur un AUTRE produit :
    les tables de sessions sont étanches, et aucun secret de session n'est partagé.
    """

    async def fetchrow(self, query: str, *args: Any) -> None:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


def identity_service(db: NoSessionDb) -> IdentityService:
    """Le VRAI service, sur une base sans pair apparié : l'état d'un module jamais apparié.

    Une doublure du service aurait prouvé le comportement de la doublure. Ici, le refus
    vient du code qui refusera en production.
    """
    return IdentityService(
        pool=cast(Any, db),
        secrets=cast(Any, None),
        cipher=cast(Any, None),
        catalog=EventTypeCatalog(code_event_types()),
        now=lambda: datetime.now(UTC),
        http=cast(Any, None),
        origin=None,
    )


async def sante() -> HealthReport:
    return HealthReport(database_reachable=True, schema_version=8, expected_schema_version=8)


def app_sous_essai(account: AdminAccount | None, tmp_path: Path) -> FastAPI:
    app = build_app()
    db = NoSessionDb()
    app.state.identity = identity_service(db)
    # Posée par la durée de vie en vrai ; ici une sonde d'essai, pour que la route
    # réponde réellement au lieu d'être seulement déclarée.
    app.state.health_probe = sante
    app.state.auth = AuthContext(
        store=AdminAccountStore(tmp_path / ".env", tmp_path / ".env.bak", account),
        db=db,
        throttle=LoginThrottle(),
        session_ttl=timedelta(hours=12),
        cookie_secure=True,
    )
    return app
