"""Génère migrations/0005_cultures.sql depuis les données CLDR de Babel.

Outil de développement, lancé une fois, jamais au démarrage du service :

    cd backend && uv run --with 'babel==2.17.0' python scripts/generate_cultures_migration.py

La migration produite est immuable dès qu'elle est jouée quelque part. Une liste
plus récente se charge par une NOUVELLE migration, pas en régénérant celle-ci.
"""

from __future__ import annotations

import sys
from pathlib import Path

import babel
from babel import Locale, localedata

BABEL_VERSION = "2.17.0"
TARGET = Path(__file__).resolve().parents[1] / "migrations" / "0005_cultures.sql"
FALLBACK = "en-US"

# Fichier SQL statique écrit une fois, depuis des constantes et les données CLDR
# échappées par _sql : ce n'est pas une requête construite à l'exécution.
HEADER = f"""-- Référentiel des cultures (décision du 20/10/2026) : la liste est DONNÉE, pas saisie.
-- Générée par scripts/generate_cultures_migration.py depuis les données CLDR de
-- Babel {BABEL_VERSION} : code BCP 47, libellé anglais et libellé dans la culture elle-même.
-- Ne pas éditer à la main ni régénérer une fois jouée : une nouvelle liste passe par
-- une nouvelle migration, qui ne touche pas à l'état actif des cultures existantes.
CREATE TABLE cultures (
    code text PRIMARY KEY CHECK (code ~ '^[a-z]{{2,3}}(-[A-Za-z0-9]{{2,8}})*$'),
    label_en text NOT NULL CHECK (char_length(label_en) BETWEEN 1 AND 200),
    label_native text NOT NULL CHECK (char_length(label_native) BETWEEN 1 AND 200),
    active boolean NOT NULL DEFAULT false,
    -- {FALLBACK} est le repli garanti de tout libellé déclinable : la base elle-même
    -- refuse de la désactiver, quoi que fasse le code.
    CONSTRAINT cultures_fallback_always_active CHECK (code <> '{FALLBACK}' OR active)
);

INSERT INTO cultures (code, label_en, label_native, active) VALUES
"""  # noqa: S608


def _sql(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def main() -> int:
    if babel.__version__ != BABEL_VERSION:
        print(f"Babel {BABEL_VERSION} attendu, {babel.__version__} trouvé", file=sys.stderr)
        return 1
    rows = []
    for identifier in sorted(localedata.locale_identifiers()):
        locale = Locale.parse(identifier)
        code = identifier.replace("_", "-")
        label_en = locale.get_display_name("en") or code
        label_native = locale.get_display_name() or label_en
        active = "true" if code == FALLBACK else "false"
        rows.append(f"    ({_sql(code)}, {_sql(label_en)}, {_sql(label_native)}, {active})")
    if not any(row.startswith(f"    ('{FALLBACK}'") for row in rows):
        print(f"{FALLBACK} absente des données CLDR : refus", file=sys.stderr)
        return 1
    TARGET.write_text(HEADER + ",\n".join(rows) + ";\n", encoding="utf-8")
    print(f"{len(rows)} cultures écrites dans {TARGET.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
