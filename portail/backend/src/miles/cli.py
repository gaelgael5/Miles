from __future__ import annotations

from miles_socle.db.cli_migrate import build_main

from miles.config import DatabaseSettings

# `miles-migrate` : la mécanique est au socle, le portail n'apporte que SA configuration
# — son préfixe d'environnement et le répertoire de ses migrations, dont le socle ne
# sait rien puisqu'il ne porte aucun SQL.
main = build_main(lambda: DatabaseSettings())  # type: ignore[call-arg]  # lu dans l'environnement
