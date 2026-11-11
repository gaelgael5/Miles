"""Génère migrations/0033_regles_de_jours_feries.sql depuis le TOC de calendarium.

Outil de développement, lancé une fois, jamais au démarrage du service :

    cd backend && uv run --with 'pycountry==24.6.1' python scripts/generate_holiday_rules_migration.py

POURQUOI UNE MIGRATION ENGENDRÉE, ET PAS UNE LECTURE DU TOC À L'EXÉCUTION. Le TOC est un
fichier distant (`DEFAULT_TOC_URL`) ou embarqué dans le paquet : le lire au démarrage
ferait dépendre l'affichage d'un réseau ou d'une version de paquet, et l'association
pays → fichier de règles changerait sous les pieds d'un administrateur sans qu'aucun commit
ne le dise. En base, chargée par une migration, elle se relit, se diffe et se révoque comme
le reste du référentiel — même dispositif que les pays (30/10/2026) et les fuseaux.

POURQUOI `pycountry` ICI ET PAS À L'EXÉCUTION. Calendarium indexe ses fichiers par NOM DE
PAYS anglais à underscores (`France`, `United_States`) ; le référentiel de Miles indexe en
ISO 3166-1 alpha-3. La correspondance entre les deux n'existe nulle part : elle se mesure
ici, une fois, et s'écrit en base. À l'exécution, plus rien à rapprocher.

LA MESURE, le 11/11/2026, sur le TOC embarqué par calendarium 0.4.0 : **111 pays vérifiés,
dont 102 s'apparient directement par leur nom** via `pycountry.countries.lookup`, et **9 ne
s'apparient pas** — ils sont listés dans `EXCEPTIONS` avec la raison de chacun. Aucune
collision d'alpha-3 : deux pays du TOC ne tombent jamais sur le même code.

POURQUOI PAS LA CULTURE DU TOC COMME CLÉ. Son champ `culture` porte un code .NET dont la
partie région RESSEMBLE à un alpha-2, et c'est un piège : `Slovenia` y est annoncée
`en-SI`, l'Inde `as-IN`, la Belgique `be` tout court — et `Russia;ru` n'a AUCUNE région.
Un repli sur la culture n'aurait donc pas sauvé les neuf cas, il en aurait fabriqué de
faux en silence. La culture n'est pas non plus stockée : rien ne la lit, ni le moteur — qui
s'interroge par nom de pays — ni le lien vers la source.

La migration produite est immuable dès qu'elle est jouée quelque part. Une version plus
récente de calendarium se charge par une NOUVELLE migration, qui ne touche pas à l'état
des pays existants — même règle que les pays et les cultures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pycountry
from calendarium import Toc, bundled_data_path

TARGET = Path(__file__).resolve().parents[1] / "migrations" / "0033_regles_de_jours_feries.sql"

# Les neuf pays du TOC que `pycountry.countries.lookup` ne retrouve pas sous leur nom
# calendarium, et l'alpha-3 de chacun. Écrits à la main parce qu'il n'existe aucune règle
# qui les dériverait : ce sont des écarts de nommage, pas un motif. Chacun a été rapproché
# en lisant la région de sa culture dans le TOC, puis vérifié contre l'ISO 3166-1 ci-dessous
# — le script REFUSE de produire quoi que ce soit si l'un d'eux cesse d'être exact.
EXCEPTIONS = {
    # Nom court là où l'ISO écrit « Brunei Darussalam ».
    "Brunei": "BRN",
    # L'ISO écrit « Congo, The Democratic Republic of the » ; à ne pas confondre avec COG.
    "Congo_Democratic_Republic_of": "COD",
    # L'ISO écrit « Holy See (Vatican City State) ».
    "Holy_See_Vatican_City": "VAT",
    # « S_A_R » rend « Special Administrative Region », que l'ISO n'emploie pas sous cette
    # forme abrégée.
    "Hong_Kong_S_A_R": "HKG",
    # « Korea » tout court désigne la Corée du SUD dans ce référentiel : son fichier porte
    # la culture `ko-KR`. La Corée du Nord n'a pas de configuration vérifiée.
    "Korea": "KOR",
    "Macao_S_A_R": "MAC",
    # « FYRO » est l'ancienne désignation ; l'ISO porte « North Macedonia » depuis 2019.
    "Macedonia_FYRO": "MKD",
    # L'ISO écrit « Russian Federation ».
    "Russia": "RUS",
    # L'ISO écrit « Türkiye » depuis 2022, que `lookup` ne retrouve plus sous « Turkey ».
    "Turkey": "TUR",
}

HEADER = """-- Règles de jours fériés : quel fichier de paramétrage de calendarium décrit chaque pays.
-- Demandé par Gael le 11/11/2026 — « utiliser le système de toc qui est dans calendarium
-- pour associer en base un fichier de paramétrage par country ».
--
-- CE QUE CETTE TABLE EST, ET CE QU'ELLE N'EST PAS. Elle porte une ASSOCIATION donnée, pas
-- un paramétrage : les règles elles-mêmes vivent dans le dépôt de calendarium, et le
-- moteur les évalue. Rien ici ne se saisit, ne se crée ni ne se supprime — comme les pays
-- et les fuseaux, c'est un référentiel DONNÉ. L'administrateur n'y fait rien du tout : il
-- active un pays dans `reference_countries`, et cette table dit où sont ses règles.
--
-- POURQUOI LE NOM DE PAYS DE CALENDARIUM EST UNE COLONNE. C'est la clé d'interrogation du
-- moteur (`get_dates(year, "France")`), et elle ne se dérive pas de l'alpha-3 : ce sont des
-- noms anglais à underscores, avec neuf écarts de nommage mesurés. La stocker, c'est
-- cesser de la recalculer — et c'est elle qui rend la ligne vérifiable à la relecture.
--
-- POURQUOI L'URL EST STOCKÉE PLUTÔT QUE CONSTRUITE. Elle vient du TOC publié par le paquet
-- (`toc.full.txt`), qui fait foi ; la reconstruire par concaténation serait inventer ce que
-- le paquet dit déjà, et le jour où l'auteur déplace ses fichiers, la migration suivante
-- porterait la vérité au lieu d'un motif périmé dans le code.
--
-- Engendré par portail/backend/scripts/generate_holiday_rules_migration.py depuis le TOC
-- embarqué par calendarium. Ne pas éditer à la main ni régénérer une fois jouée.
CREATE TABLE reference_country_holidays (
    -- Le pays de Miles. Clé ÉTRANGÈRE : une règle qui désignerait un code absent du
    -- référentiel serait inévaluable, et rien ne le dirait avant qu'un écran ne reste vide.
    -- Aucun ON DELETE : un pays ne se supprime jamais, et écrire une cascade laisserait
    -- croire le contraire.
    slug text PRIMARY KEY REFERENCES reference_countries (slug),
    -- La clé d'interrogation du moteur. UNIQUE : deux pays de Miles qui pointeraient le
    -- même fichier de règles afficheraient les mêmes jours pour deux pays différents.
    calendarium_country text NOT NULL UNIQUE CHECK (calendarium_country ~ '^[A-Za-z_]+$'),
    -- L'URL brute du fichier de règles, telle que le TOC la publie. La page GitHub
    -- navigable s'en dérive à l'affichage (`reference/holidays.py`).
    source_url text NOT NULL CHECK (source_url LIKE 'https://%')
);

INSERT INTO reference_country_holidays (slug, calendarium_country, source_url) VALUES
"""


def alpha3_of(country: str) -> str | None:
    """L'alpha-3 d'un nom de pays calendarium. None s'il ne se rapproche de rien.

    Les exceptions passent AVANT la recherche par nom : `lookup` pourrait se mettre à
    retrouver l'un d'eux à la faveur d'une montée de `pycountry`, et c'est alors la valeur
    mesurée qui doit gagner, pas celle qu'une bibliothèque vient de changer d'avis.
    """
    exception = EXCEPTIONS.get(country)
    if exception is not None:
        return exception
    try:
        return str(pycountry.countries.lookup(country.replace("_", " ")).alpha_3)
    except LookupError:
        return None


def main() -> int:
    base = Path(bundled_data_path() if callable(bundled_data_path) else bundled_data_path)
    # `toc.full.txt` et non `toc.txt` : le premier porte les URL absolues du dépôt, le
    # second des chemins relatifs que `Toc.load` résout en chemins LOCAUX de la machine qui
    # génère. Mesuré le 11/11/2026 — c'est exactement le piège qui aurait mis
    # « /home/.../site-packages/... » en base.
    toc = Toc.load(base / "toc.full.txt")
    lignes, inconnus, inutiles = [], [], set(EXCEPTIONS)
    for entry in sorted(toc.entries, key=lambda e: e.country):
        inutiles.discard(entry.country)
        alpha3 = alpha3_of(entry.country)
        if alpha3 is None:
            inconnus.append(entry.country)
            continue
        if not entry.uri.startswith("https://"):
            print(f"URI non absolue pour {entry.country} : {entry.uri!r}", file=sys.stderr)
            return 1
        if "'" in entry.uri or "'" in entry.country:
            # Ces deux valeurs partent dans un littéral SQL : c'est la seule garde entre le
            # TOC et le texte produit. Aucun des 111 noms n'en porte, et si cela changeait
            # il faut le voir plutôt que produire un fichier cassé.
            print(f"apostrophe inattendue dans {entry.country!r}", file=sys.stderr)
            return 1
        lignes.append(f"    ('{alpha3}', '{entry.country}', '{entry.uri}')")
    if inconnus:
        # Un pays que rien ne rapproche ne s'ignore PAS : il manquerait de l'écran sans
        # qu'aucun message ne le dise. Il faut l'ajouter à EXCEPTIONS, à la main et en
        # écrivant pourquoi.
        print(f"{len(inconnus)} pays sans alpha-3 : {', '.join(inconnus)}", file=sys.stderr)
        return 1
    if inutiles:
        # Une exception qui ne sert plus est une affirmation périmée : elle survivrait au
        # motif qui l'a justifiée, et personne ne saurait plus si elle protège quelque chose.
        print(f"exceptions devenues inutiles : {', '.join(sorted(inutiles))}", file=sys.stderr)
        return 1
    if len(lignes) < 100:
        print(f"liste trop courte : {len(lignes)} pays", file=sys.stderr)
        return 1
    TARGET.write_text(HEADER + ",\n".join(lignes) + ";\n", encoding="utf-8")
    print(f"{TARGET.name} : {len(lignes)} pays, dont {len(EXCEPTIONS)} par exception")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
