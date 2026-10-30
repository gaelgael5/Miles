"""Génère migrations/0029_referentiel_des_fuseaux.sql depuis la table IANA `zone1970.tab`.

Outil de développement, lancé une fois, jamais au démarrage du service :

    cd backend && uv run --with 'pycountry==24.6.1' python scripts/generate_timezones_migration.py

POURQUOI `zone1970.tab` ET PAS LES DONNÉES CLDR. Trois mesures du 30/10/2026 :

- la table IANA ne contient que les zones **canoniques** — 312 —, là où
  `zoneinfo.available_timezones()` en rend 486 en mélangeant les noms obsolètes (et
  `localtime`, qui n'est pas un fuseau). Charger les deux noms d'un même lieu ferait deux
  lignes à cocher pour un seul fuseau ;
- elle porte **tous** les pays de chaque zone, dans son ordre : `Asia/Dubai` en a cinq,
  `Europe/Brussels` trois. Ne garder que le premier laisserait **93 pays** sans aucun
  fuseau, dont le Luxembourg et les Pays-Bas ;
- `zone_aliases` de CLDR ne sert PAS à écarter les alias : il va du nom canonique vers
  l'ancien (`Europe/Kyiv` → `Europe/Kiev`). Filtrer sur ses clés retirerait les bons noms.

CLDR reste la source des LIBELLÉS, dérivés à l'exécution comme pour les pays.

RIEN N'EST AJOUTÉ À LA TABLE, et `UTC` en particulier. Il avait été retenu d'abord, puis
mesuré : CLDR n'en a aucun nom et rend son format de repli — « heure : région indéterminée
(UTC) », ce qui est laid et faux. La table IANA l'exclut pour une raison qui vaut aussi
ici : ce référentiel qualifie des LIEUX, et UTC n'est pas un lieu. La famille `Etc/GMT±N`
est écartée pour une autre raison : ses signes sont inversés (`Etc/GMT+1` vaut UTC moins 1),
c'est un piège connu, et personne ne l'écrit dans une procédure.

CONSÉQUENCE MESURÉE : chaque zone de la table porte au moins un pays, donc le référentiel
n'a aucune entrée sans pays. Le critère qui prévoyait ce cas venait d'une mesure CLDR
(`Antarctica/Troll` rattaché au monde) que la source IANA rend fausse — elle lui donne AQ.

La migration produite est immuable dès qu'elle est jouée. La base IANA change plusieurs
fois par an : une liste plus récente passe par une NOUVELLE migration, qui ne touche pas à
l'état actif des fuseaux existants.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pycountry

TABLE = Path("/usr/share/zoneinfo/zone1970.tab")
TARGET = Path(__file__).resolve().parents[1] / "migrations" / "0029_referentiel_des_fuseaux.sql"
SLUG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+/-]{1,99}$")

HEADER = """-- Référentiel des fuseaux horaires : la liste est DONNÉE, pas saisie. L'administrateur
-- ACTIVE ceux dont son installation se sert — même dispositif que les cultures et les pays.
--
-- SOURCE : la table IANA `zone1970.tab`, et non les données CLDR. Elle ne contient que les
-- zones CANONIQUES (312, contre 486 identifiants dont les noms obsolètes), et elle porte
-- TOUS les pays de chaque zone. Mesuré le 30/10/2026 : `zone_aliases` de CLDR va du nom
-- canonique vers l'ancien (`Europe/Kyiv` → `Europe/Kiev`), donc il ne sert pas à écarter
-- les alias — il retirerait les bons noms.
--
-- POURQUOI UN LIEN N-N VERS LES PAYS. `Asia/Dubai` sert cinq pays, `Europe/Brussels` trois.
-- Mesuré : 93 pays n'apparaissent JAMAIS en première position, donc ne garder que le pays
-- « principal » les laisserait tous sans aucun fuseau — le Luxembourg, les Pays-Bas, Oman.
--
-- POURQUOI AUCUN LIBELLÉ ICI, ni aucun décalage horaire. Les libellés sont dérivés de CLDR
-- au moment d'afficher, dans la culture du visiteur (même raison que les pays). Le décalage,
-- lui, dépend de la date et des règles d'heure d'été, qui changent plusieurs fois par an :
-- une valeur stockée serait fausse six mois sur douze, et fausse en silence.
--
-- Engendré par portail/backend/scripts/generate_timezones_migration.py. Ne pas éditer à la
-- main ni régénérer une fois jouée.
CREATE TABLE reference_timezones (
    -- L'identifiant IANA, qui est ce qu'une procédure écrit et ce que lit tout système.
    -- Le libellé localisé de CLDR ne le remplace pas : « heure d'Europe centrale » vaut
    -- pour Paris, Berlin et Madrid à la fois, donc il ne désigne aucun fuseau.
    slug text PRIMARY KEY CHECK (slug ~ '^[A-Za-z][A-Za-z0-9_+/-]{1,99}$'),
    -- Aucun fuseau actif à l'installation, comme pour les pays : l'état neuf est « aucun
    -- fuseau retenu », pas « tous ».
    active boolean NOT NULL DEFAULT false
);

-- Les pays d'un fuseau. Une table de lien, parce que la relation est N-N dans le standard.
CREATE TABLE reference_timezone_countries (
    timezone_slug text NOT NULL REFERENCES reference_timezones (slug) ON DELETE CASCADE,
    -- Pointe le référentiel des pays par son slug alpha-3 : la base refuse donc un pays
    -- qui n'existe pas, et les deux référentiels ne peuvent pas se contredire.
    country_slug text NOT NULL REFERENCES reference_countries (slug),
    -- L'ordre d'IANA. Le premier pays cité est celui que la table met en tête, et c'est
    -- celui qu'un écran nomme quand il n'en montre qu'un. Sans cette colonne, l'ordre
    -- serait celui que la base rend, qui ne veut rien dire.
    rank integer NOT NULL CHECK (rank >= 1),
    PRIMARY KEY (timezone_slug, country_slug)
);

INSERT INTO reference_timezones (slug) VALUES
"""


def main() -> int:
    if not TABLE.is_file():
        print(f"table IANA absente : {TABLE}", file=sys.stderr)
        return 1
    alpha3 = {pays.alpha_2: pays.alpha_3 for pays in pycountry.countries}
    zones: list[str] = []
    liens: list[tuple[str, str, int]] = []
    for ligne in TABLE.read_text(encoding="utf-8").splitlines():
        if ligne.startswith("#") or not ligne.strip():
            continue
        champs = ligne.split("\t")
        if len(champs) < 3:
            print(f"ligne inattendue : {ligne!r}", file=sys.stderr)
            return 1
        codes, zone = champs[0].split(","), champs[2]
        if not SLUG_RE.match(zone):
            print(f"identifiant de fuseau inattendu : {zone!r}", file=sys.stderr)
            return 1
        zones.append(zone)
        for rang, code in enumerate(codes, start=1):
            if code not in alpha3:
                # Vérifié plutôt que supposé : un code hors ISO ferait échouer la clé
                # étrangère au moment de jouer la migration, bien plus loin de sa cause.
                print(f"code pays hors ISO 3166 : {code!r} pour {zone}", file=sys.stderr)
                return 1
            liens.append((zone, alpha3[code], rang))
    if len(zones) < 300 or len(liens) < 300:
        print(f"liste trop courte : {len(zones)} fuseaux, {len(liens)} liens", file=sys.stderr)
        return 1
    corps = HEADER + ",\n".join(f"    ('{zone}')" for zone in sorted(zones)) + ";\n"
    corps += (
        "\nINSERT INTO reference_timezone_countries (timezone_slug, country_slug, rank) VALUES\n"
    )
    corps += (
        ",\n".join(f"    ('{zone}', '{pays}', {rang})" for zone, pays, rang in sorted(liens))
        + ";\n"
    )
    TARGET.write_text(corps, encoding="utf-8")
    print(f"{TARGET.name} : {len(zones)} fuseaux, {len(liens)} liens vers les pays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
