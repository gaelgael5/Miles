from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from miles_socle.testing.files import ADMIN_PASSWORD, ADMIN_USERNAME, BASE_ENV, admin_env, write_env
from miles_socle.testing.stack import SocleStack, open_socle_stack, utc_now

from enrolement.app import build_app
from enrolement.config import DEFAULT_MIGRATIONS_DIR
from enrolement.event_types import code_event_types

# Réexportés : les tests d'intégration du produit s'en servent, et ils viennent du socle
# parce que la forme du `.env` et le compte d'amorçage sont imposés par lui, pas choisis ici.
__all__ = [
    "ADMIN_PASSWORD",
    "ADMIN_USERNAME",
    "BASE_ENV",
    "EnrolementStack",
    "admin_env",
    "open_stack",
    "utc_now",
    "write_env",
]

BASE_URL = "http://enrolement"
PUBLIC_URL = "http://enrolement.test"
ADMIN_EMAIL = "admin@enrolement.invalid"

# La coquille n'ajoute aucun service aux sept du socle : son montage EST celui du socle.
# Nommé ici pour que les tests du produit continuent de parler de leur produit, et pour
# que le jour où l'enrôlement ajoute un service — le référentiel des devices, la route de
# pair du ticket 6a0daab6 — il ait l'endroit où le câbler.
EnrolementStack = SocleStack


@asynccontextmanager
async def open_stack(
    dsn: str,
    tmp_path: Path,
    *,
    admin_email: str | None = ADMIN_EMAIL,
    public_url: str = PUBLIC_URL,
) -> AsyncIterator[EnrolementStack]:
    """Monte le produit sur une base réelle, sans passer par uvicorn.

    Les sept services du socle sont câblés par `open_socle_stack`, une fois pour les trois
    produits. La garde de `test_cablage_pg.py` vérifie que rien de ce que pose `app.py` ne
    manque au montage — c'est elle qui remplace le « après tout ajout à `app.py`, vérifier
    ici » que ce fichier portait, et que LESSONS.md a vu échouer deux fois.

    `admin_email=None` monte une installation NEUVE, sans administrateur : c'est l'état
    dans lequel l'écran d'amorçage est ouvert, et le seul où il l'est.
    """
    async with open_socle_stack(
        dsn=dsn,
        tmp_path=tmp_path,
        build_app=build_app,
        migrations_dir=DEFAULT_MIGRATIONS_DIR,
        event_types=code_event_types(),
        base_url=BASE_URL,
        public_url=public_url,
        admin_email=admin_email,
    ) as socle:
        yield socle
