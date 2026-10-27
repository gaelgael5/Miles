from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from miles.api_health import router
from miles.health import HealthReport, resolve_health
from tests.conftest import FakeConnection


class FakePool:
    def __init__(self, conn: FakeConnection | None = None, error: Exception | None = None):
        self._conn = conn
        self._error = error

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        if self._error is not None:
            raise self._error
        yield self._conn


@pytest.mark.parametrize(
    ("reachable", "version", "expected"),
    [(True, 3, True), (True, 2, False), (True, None, False), (False, None, False)],
)
def test_health_report_healthy_only_when_reachable_and_up_to_date(
    reachable: bool, version: int | None, expected: bool
) -> None:
    assert HealthReport(reachable, version, 3).healthy is expected


async def test_resolve_health_database_up_reports_version() -> None:
    conn = FakeConnection(rows=[{"version": 1, "checksum": "a"}])

    report = await resolve_health(FakePool(conn), 1, timeout_s=1.0)  # type: ignore[arg-type]

    assert report == HealthReport(True, 1, 1)


@pytest.mark.parametrize("error", [OSError("refused"), TimeoutError()])
async def test_resolve_health_database_down_reports_unreachable(error: Exception) -> None:
    report = await resolve_health(FakePool(error=error), 1, timeout_s=1.0)  # type: ignore[arg-type]

    assert report == HealthReport(False, None, 1)


def _client(report: HealthReport) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    async def probe() -> HealthReport:
        return report

    app.state.health_probe = probe
    return TestClient(app)


def test_get_health_up_to_date_returns_200() -> None:
    response = _client(HealthReport(True, 4, 4)).get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "up",
        "schema_version": 4,
        "expected_schema_version": 4,
    }


def test_get_health_schema_behind_returns_503() -> None:
    response = _client(HealthReport(True, 3, 4)).get("/api/health")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "up"


def test_get_health_database_down_returns_503() -> None:
    response = _client(HealthReport(False, None, 4)).get("/api/health")

    assert response.status_code == 503
    assert response.json()["database"] == "down"
    assert response.json()["schema_version"] is None
