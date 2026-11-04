from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from miles_socle.auth.admin_account import AdminAccount
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.context import AuthContext
from miles_socle.auth.gate import auth_gate
from miles_socle.auth.passwords import hash_password
from miles_socle.auth.throttle import LoginThrottle
from miles_socle.journal.api_journal import MAINTENANCE_PATH
from miles_socle.journal.api_journal import router as journal_router
from miles_socle.journal.maintenance import MaintenanceReport, TableReport

JETON = "jeton-d-entretien-de-la-stack"
RAPPORT = MaintenanceReport(
    day=date(2026, 11, 3),
    retention_days=30,
    tables=(
        TableReport("event_objects", (date(2026, 11, 10),), (), 31),
        TableReport("events", (date(2026, 11, 10),), (date(2026, 10, 3),), 30),
    ),
)


class _NoSessionDb:
    async def fetchrow(self, query: str, *args: Any) -> None:
        return None

    async def execute(self, query: str, *args: Any) -> str:
        return "OK"


@dataclass
class _Entretien:
    """Doublure du service : la route ne doit rien savoir de PostgreSQL.

    Elle compte ses appels, parce qu'un refus qui entretiendrait quand même serait un
    défaut invisible dans le corps de la réponse.
    """

    appels: int = 0

    async def resolve_maintain(self) -> MaintenanceReport:
        self.appels += 1
        return RAPPORT


def _app(tmp_path: Path, *, jeton: str | None, systeme: bool = True) -> tuple[FastAPI, _Entretien]:
    app = FastAPI()
    app.middleware("http")(auth_gate)
    app.include_router(journal_router)
    entretien = _Entretien()
    app.state.journal_maintenance = entretien
    app.state.journal_maintenance_token = jeton
    if systeme:
        app.state.system_api_paths = frozenset({MAINTENANCE_PATH})
    app.state.auth = AuthContext(
        store=AdminAccountStore(
            tmp_path / ".env",
            tmp_path / ".env.bak",
            AdminAccount(
                email="admin@essai.invalid",
                username="admin",
                password_hash=SecretStr(hash_password("mot-de-passe-d-essai-suffisant")),
            ),
        ),
        db=_NoSessionDb(),
        throttle=LoginThrottle(),
        session_ttl=timedelta(hours=1),
        cookie_secure=True,
    )
    return app, entretien


def _appel(client: TestClient, jeton: str | None) -> Any:
    entetes = {"Authorization": f"Bearer {jeton}"} if jeton is not None else {}
    return client.post(MAINTENANCE_PATH, headers=entetes)


class TestLePortillon:
    def test_sans_declaration_systeme_la_route_n_est_meme_pas_atteinte(
        self, tmp_path: Path
    ) -> None:
        """Le défaut est l'ensemble VIDE : rien ne s'ouvre parce que le passage existe."""
        app, entretien = _app(tmp_path, jeton=JETON, systeme=False)

        reponse = _appel(TestClient(app), JETON)

        assert reponse.status_code == 401
        assert reponse.json() == {"detail": "session_requise"}
        assert entretien.appels == 0


class TestLeJeton:
    def test_le_bon_jeton_entretient_et_rend_le_rapport(self, tmp_path: Path) -> None:
        app, entretien = _app(tmp_path, jeton=JETON)

        reponse = _appel(TestClient(app), JETON)

        assert reponse.status_code == 200
        assert entretien.appels == 1
        assert reponse.json() == {
            "day": "2026-11-03",
            "retention_days": 30,
            "changed": True,
            "tables": [
                {
                    "table": "event_objects",
                    "created": ["2026-11-10"],
                    "dropped": [],
                    "remaining": 31,
                },
                {
                    "table": "events",
                    "created": ["2026-11-10"],
                    "dropped": ["2026-10-03"],
                    "remaining": 30,
                },
            ],
        }

    def test_un_jeton_non_configure_refuse_TOUT_et_n_entretient_pas(self, tmp_path: Path) -> None:
        """Fail closed : une stack sans jeton a une route d'entretien inerte."""
        app, entretien = _app(tmp_path, jeton=None)

        reponse = _appel(TestClient(app), JETON)

        assert reponse.status_code == 401
        assert reponse.json() == {"detail": "jeton_requis"}
        assert entretien.appels == 0

    def test_un_jeton_vide_en_configuration_vaut_absent(self, tmp_path: Path) -> None:
        """Sinon `Authorization: Bearer ` présenterait vide et ouvrirait tout."""
        app, entretien = _app(tmp_path, jeton="")

        assert _appel(TestClient(app), "").status_code == 401
        assert entretien.appels == 0

    @pytest.mark.parametrize(
        "entete",
        [
            None,
            "",
            "Bearer",
            "Bearer ",
            "Bearer autre-jeton",
            f"Basic {JETON}",
            JETON,
            f"bearer {JETON[:-1]}",
        ],
    )
    def test_tout_ce_qui_n_est_pas_EXACTEMENT_le_jeton_est_refuse(
        self, tmp_path: Path, entete: str | None
    ) -> None:
        app, entretien = _app(tmp_path, jeton=JETON)
        entetes = {} if entete is None else {"Authorization": entete}

        reponse = TestClient(app).post(MAINTENANCE_PATH, headers=entetes)

        assert reponse.status_code == 401
        assert reponse.headers["WWW-Authenticate"] == 'Bearer realm="miles-journal"'
        assert entretien.appels == 0

    def test_le_schema_bearer_est_insensible_a_la_casse(self, tmp_path: Path) -> None:
        app, _ = _app(tmp_path, jeton=JETON)

        reponse = TestClient(app).post(
            MAINTENANCE_PATH, headers={"Authorization": f"bEaReR {JETON}"}
        )

        assert reponse.status_code == 200


def test_un_passage_sans_rien_pose_n_ecrit_pas_dans_le_journal_d_exploitation() -> None:
    """`changed` est FAUX quand rien n'a bougé : tout le SQL est idempotent, donc le
    succès ne dit rien de l'effet (leçon du 02/11/2026)."""
    rien = MaintenanceReport(
        day=datetime(2026, 11, 3, tzinfo=UTC).date(),
        retention_days=None,
        tables=(TableReport("events", (), (), 8),),
    )

    assert rien.changed is False
    assert RAPPORT.changed is True
