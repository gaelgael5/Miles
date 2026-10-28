from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest


def _admin_dsn() -> str:
    # Pas de repli : lancés sans base, ces tests doivent échouer, pas se déclarer verts.
    dsn = os.environ.get("MILES_TEST_DATABASE_URL")
    if not dsn:
        pytest.fail("MILES_TEST_DATABASE_URL absent : les tests d'intégration exigent PostgreSQL")
    return dsn


@pytest.fixture
async def blank_db() -> AsyncIterator[str]:
    """Une base vierge par test, détruite après : jamais de base partagée entre exécutions."""
    admin_dsn = _admin_dsn()
    name = f"environnement_test_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f'CREATE DATABASE "{name}"')  # nom généré ci-dessus, pas une entrée
    try:
        yield admin_dsn.rsplit("/", 1)[0] + f"/{name}"
    finally:
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()
