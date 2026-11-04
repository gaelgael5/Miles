"""Base jetable par test, pour les suites d'intégration des trois produits."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable

import asyncpg
import pytest

DSN_ENV = "MILES_TEST_DATABASE_URL"


async def open_blank_db(prefix: str) -> AsyncIterator[str]:
    """Crée une base vierge, rend son DSN, la détruit à la sortie.

    Une base par test, jamais partagée : deux exécutions concurrentes sur la même base
    jetable se détruisent mutuellement.

    Écrit comme un générateur ordinaire et non directement comme une fixture : c'est ce qui
    permet de l'éprouver sans PostgreSQL, et donc de vérifier que le préfixe du produit est
    bien employé — ce pour quoi la fabrique ci-dessous existe.
    """
    # Pas de repli : lancés sans base, ces tests doivent échouer, pas se déclarer verts.
    admin_dsn = os.environ.get(DSN_ENV)
    if not admin_dsn:
        pytest.fail(f"{DSN_ENV} absent : les tests d'intégration exigent PostgreSQL")
    name = f"{prefix}_{uuid.uuid4().hex[:12]}"
    admin = await asyncpg.connect(admin_dsn)
    # Nom engendré juste au-dessus, jamais une entrée : rien à échapper ici.
    await admin.execute(f'CREATE DATABASE "{name}"')
    try:
        yield admin_dsn.rsplit("/", 1)[0] + f"/{name}"
    finally:
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()


def blank_db_fixture(prefix: str) -> Callable[[], AsyncIterator[str]]:
    """Fabrique la fixture `blank_db` d'un produit, avec SON préfixe de nom de base.

    Une fabrique plutôt qu'une fixture toute faite : le préfixe nomme le produit, et une
    base oubliée sur la machine de test doit dire d'où elle vient. Le produit écrit donc
    `blank_db = blank_db_fixture("environnement_test")` dans son conftest d'intégration —
    une ligne, et pytest l'enregistre comme n'importe quelle fixture locale.
    """

    @pytest.fixture(name="blank_db")
    async def fixture() -> AsyncIterator[str]:
        async for dsn in open_blank_db(prefix):
            yield dsn

    return fixture
