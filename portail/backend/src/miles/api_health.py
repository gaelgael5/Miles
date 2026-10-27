from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict

from miles.health import HealthProbe

router = APIRouter()


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    database: Literal["up", "down"]
    schema_version: int | None
    expected_schema_version: int


def _probe(request: Request) -> HealthProbe:
    probe: HealthProbe = request.app.state.health_probe
    return probe


@router.get("/api/health", response_model=HealthResponse)
async def get_health(request: Request, response: Response) -> HealthResponse:
    report = await _probe(request)()
    # 503 et non 200 « dégradé » : le script de déploiement et tout superviseur
    # lisent le code HTTP, pas le corps.
    if not report.healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if report.healthy else "degraded",
        database="up" if report.database_reachable else "down",
        schema_version=report.schema_version,
        expected_schema_version=report.expected_schema_version,
    )
