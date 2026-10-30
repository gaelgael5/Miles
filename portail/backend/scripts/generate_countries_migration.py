"""Génère migrations/0028_referentiel_des_pays.sql depuis l'ISO 3166-1.

Outil de développement, lancé une fois, jamais au démarrage du service :

    cd backend && uv run --with 'pycountry==24.6.1' python scripts/generate_countries_migration.py

POURQUOI `pycountry` ICI ET PAS À L'EXÉCUTION. Le slug demandé est l'alpha-3 ; CLDR, qui
donne les libellés, indexe les territoires en alpha-2. La correspondance entre les deux est
dans l'ISO 3166, que `pycountry` porte — et une fois écrite en base, elle n'a plus à être
recalculée. Babel, lui, reste nécessaire à l'exécution, parce que les libellés dépendent de
la culture du visiteur, qui n'est pas connue ici.

La migration produite est immuable dès qu'elle est jouée quelque part. Une liste plus
récente se charge par une NOUVELLE migration, qui ne touche pas à l'état actif des pays
existants — même règle que les cultures (décision du 20/10/2026).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pycountry

TARGET = Path(__file__).resolve().parents[1] / "migrations" / "0028_referentiel_des_pays.sql"

# Fichier SQL statique écrit une fois, depuis des constantes et des codes ISO vérifiés par
# regex ci-dessous : ce n'est pas une requête construite à l'exécution.
HEADER = """-- Référentiel des pays : la liste est DONNÉE, pas saisie. L'administrateur ACTIVE ceux
-- dont son installation se sert, depuis un écran muni d'un filtre — même dispositif que les
-- cultures (tranché par Gael le 15/10/2026, repris pour les pays le 30/10/2026).
--
-- POURQUOI DEUX CODES SUR LA MÊME LIGNE. Le slug est l'ISO 3166-1 ALPHA-3, parce que c'est
-- ce que Gael a demandé et ce que les procédures d'exploitation écrivent. Mais CLDR, qui
-- donne les libellés, indexe les territoires en ALPHA-2 : sans lui sur la ligne, aucun
-- libellé n'est dérivable. L'alpha-2 est donc une donnée du référentiel, pas une commodité.
--
-- POURQUOI AUCUN LIBELLÉ ICI. Ils sont dérivés de CLDR au moment d'afficher, dans la
-- culture du visiteur. Les charger aurait voulu dire choisir POUR QUELLES cultures : les
-- 249 pays × les ~800 cultures du référentiel font deux cent mille lignes de SQL, et s'en
-- tenir aux langues laisse sans libellé toute culture non prévue. Activer une culture de
-- plus donne ainsi aussitôt ses libellés, sans migration ni saisie.
--
-- Engendré par portail/backend/scripts/generate_countries_migration.py depuis
-- l'ISO 3166-1 (pycountry). Ne pas éditer à la main ni régénérer une fois jouée.
CREATE TABLE reference_countries (
    -- ISO 3166-1 alpha-3. La base refuse toute autre forme : un slug en alpha-2 glissé
    -- ici serait introuvable par qui écrit une procédure, et le libellé dérivé serait faux.
    slug text PRIMARY KEY CHECK (slug ~ '^[A-Z]{3}$'),
    -- La clé de lecture de CLDR. UNIQUE parce que deux pays ne partagent pas un alpha-2 :
    -- s'ils le faisaient, l'un des deux porterait le libellé de l'autre.
    alpha2 text NOT NULL UNIQUE CHECK (alpha2 ~ '^[A-Z]{2}$'),
    -- Aucun pays actif à l'installation : l'état neuf est « aucun pays retenu », pas
    -- « tous ». Une liste entière proposée par défaut rendrait l'activation inutile.
    active boolean NOT NULL DEFAULT false
);

INSERT INTO reference_countries (slug, alpha2) VALUES
"""


def main() -> int:
    lignes = []
    for pays in sorted(pycountry.countries, key=lambda c: c.alpha_3):
        alpha3, alpha2 = pays.alpha_3, pays.alpha_2
        # Vérifié plutôt que supposé : ces deux valeurs partent dans un fichier SQL, et
        # c'est la seule garde entre la bibliothèque et le texte produit.
        if not (len(alpha3) == 3 and alpha3.isascii() and alpha3.isupper()):
            print(f"code alpha-3 inattendu : {alpha3!r}", file=sys.stderr)
            return 1
        if not (len(alpha2) == 2 and alpha2.isascii() and alpha2.isupper()):
            print(f"code alpha-2 inattendu : {alpha2!r}", file=sys.stderr)
            return 1
        lignes.append(f"    ('{alpha3}', '{alpha2}')")
    if len(lignes) < 200:
        print(f"liste trop courte : {len(lignes)} pays", file=sys.stderr)
        return 1
    TARGET.write_text(HEADER + ",\n".join(lignes) + ";\n", encoding="utf-8")
    print(f"{TARGET.name} : {len(lignes)} pays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
