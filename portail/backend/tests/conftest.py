from __future__ import annotations

from miles_socle.testing import FakeConnection, write_migrations
from miles_socle.testing.fixtures import fake_conn, two_migrations

# Fixtures et doublures communes aux trois produits, portées par le socle. Importées et non
# redéfinies — l'import suffit à pytest pour enregistrer les fixtures —, et réexportées
# parce que quatre fichiers de test les prennent dans ce conftest : un refactoring ne
# réécrit pas les tests.
__all__ = ["FakeConnection", "fake_conn", "two_migrations", "write_migrations"]
