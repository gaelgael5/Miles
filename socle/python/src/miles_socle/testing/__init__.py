"""Matériel de test partagé par les suites du socle et des trois produits.

Livré DANS le paquet et non dans ses tests : les trois produits ont chacun leur
environnement et leur suite, et aucun ne peut importer les tests d'un autre. Recopier une
doublure, une fixture ou un montage dans chaque suite les fait diverger de ce qu'ils
imitent — et c'est arrivé. Pendant du `@miles/socle-web/testing` côté front.

Ce module ne réexporte que ce qui ne demande ni pytest ni httpx, de sorte qu'un import
depuis l'image de production — où ces paquets ne sont pas installés — ne casse pas. Les
fixtures (`testing.db`) et le montage (`testing.stack`) s'importent par leur chemin, et
l'extra `miles-socle[testing]` déclare ce qu'ils exigent.
"""

from __future__ import annotations

from miles_socle.testing.doubles import FakeClock, FakeConnection, FakeSessionDb
from miles_socle.testing.files import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    BASE_ENV,
    DSN,
    SECRETS_KEY,
    admin_env,
    write_env,
    write_migrations,
)
from miles_socle.testing.wiring import (
    assert_harness_wires_everything,
    file_lifespan_wirings,
    file_wirings,
    resolve_missing_wirings,
)

__all__ = [
    "ADMIN_PASSWORD",
    "ADMIN_USERNAME",
    "BASE_ENV",
    "DSN",
    "SECRETS_KEY",
    "FakeClock",
    "FakeConnection",
    "FakeSessionDb",
    "admin_env",
    "assert_harness_wires_everything",
    "file_lifespan_wirings",
    "file_wirings",
    "resolve_missing_wirings",
    "write_env",
    "write_migrations",
]
