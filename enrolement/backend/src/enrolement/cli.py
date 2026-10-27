from __future__ import annotations

from miles_socle.db.cli_migrate import build_main

from enrolement.config import DatabaseSettings

# `enrolement-migrate` : la mécanique est au socle, le produit n'apporte que SA
# configuration — son préfixe d'environnement et le répertoire de ses migrations, dont le
# socle ne sait rien puisqu'il ne porte aucun SQL.
main = build_main(lambda: DatabaseSettings())  # type: ignore[call-arg]  # lu dans l'environnement
