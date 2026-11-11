-- Règles de jours fériés : quel fichier de paramétrage de calendarium décrit chaque pays.
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
    ('ALB', 'Albania', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Albania.json'),
    ('DZA', 'Algeria', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Algeria.json'),
    ('AND', 'Andorra', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Andorra.json'),
    ('AGO', 'Angola', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Angola.json'),
    ('ARG', 'Argentina', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Argentina.json'),
    ('ARM', 'Armenia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Armenia.json'),
    ('AUS', 'Australia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Australia.json'),
    ('AUT', 'Austria', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Austria.json'),
    ('AZE', 'Azerbaijan', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Azerbaijan.json'),
    ('BHR', 'Bahrain', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Bahrain.json'),
    ('BLR', 'Belarus', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Belarus.json'),
    ('BEL', 'Belgium', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Belgium.json'),
    ('BOL', 'Bolivia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Bolivia.json'),
    ('BIH', 'Bosnia_and_Herzegovina', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Bosnia_and_Herzegovina.json'),
    ('BRA', 'Brazil', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Brazil.json'),
    ('BRN', 'Brunei', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Brunei.json'),
    ('BGR', 'Bulgaria', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Bulgaria.json'),
    ('CAN', 'Canada', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Canada.json'),
    ('CHL', 'Chile', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Chile.json'),
    ('CHN', 'China', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_China.json'),
    ('COL', 'Colombia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Colombia.json'),
    ('COD', 'Congo_Democratic_Republic_of', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Congo_Democratic_Republic_of.json'),
    ('CRI', 'Costa_Rica', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Costa_Rica.json'),
    ('HRV', 'Croatia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Croatia.json'),
    ('CYP', 'Cyprus', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Cyprus.json'),
    ('CZE', 'Czechia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Czechia.json'),
    ('DNK', 'Denmark', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Denmark.json'),
    ('DOM', 'Dominican_Republic', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Dominican_Republic.json'),
    ('ECU', 'Ecuador', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Ecuador.json'),
    ('EGY', 'Egypt', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Egypt.json'),
    ('SLV', 'El_Salvador', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_El_Salvador.json'),
    ('GNQ', 'Equatorial_Guinea', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Equatorial_Guinea.json'),
    ('EST', 'Estonia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Estonia.json'),
    ('FIN', 'Finland', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Finland.json'),
    ('FRA', 'France', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_France.json'),
    ('GEO', 'Georgia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Georgia.json'),
    ('DEU', 'Germany', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Germany.json'),
    ('GRC', 'Greece', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Greece.json'),
    ('GTM', 'Guatemala', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Guatemala.json'),
    ('VAT', 'Holy_See_Vatican_City', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Holy_See_Vatican_City.json'),
    ('HND', 'Honduras', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Honduras.json'),
    ('HKG', 'Hong_Kong_S_A_R', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Hong_Kong_S_A_R.json'),
    ('HUN', 'Hungary', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Hungary.json'),
    ('ISL', 'Iceland', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Iceland.json'),
    ('IND', 'India', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_India.json'),
    ('IRN', 'Iran', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Iran.json'),
    ('IRQ', 'Iraq', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Iraq.json'),
    ('IRL', 'Ireland', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Ireland.json'),
    ('ISR', 'Israel', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Israel.json'),
    ('ITA', 'Italy', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Italy.json'),
    ('JAM', 'Jamaica', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Jamaica.json'),
    ('JPN', 'Japan', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Japan.json'),
    ('JOR', 'Jordan', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Jordan.json'),
    ('KAZ', 'Kazakhstan', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Kazakhstan.json'),
    ('KEN', 'Kenya', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Kenya.json'),
    ('KOR', 'Korea', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Korea.json'),
    ('KWT', 'Kuwait', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Kuwait.json'),
    ('LVA', 'Latvia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Latvia.json'),
    ('LBN', 'Lebanon', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Lebanon.json'),
    ('LIE', 'Liechtenstein', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Liechtenstein.json'),
    ('LTU', 'Lithuania', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Lithuania.json'),
    ('LUX', 'Luxembourg', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Luxembourg.json'),
    ('MAC', 'Macao_S_A_R', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Macao_S_A_R.json'),
    ('MKD', 'Macedonia_FYRO', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Macedonia_FYRO.json'),
    ('MYS', 'Malaysia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Malaysia.json'),
    ('MLT', 'Malta', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Malta.json'),
    ('MEX', 'Mexico', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Mexico.json'),
    ('MDA', 'Moldova', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Moldova.json'),
    ('MCO', 'Monaco', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Monaco.json'),
    ('MNE', 'Montenegro', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Montenegro.json'),
    ('MAR', 'Morocco', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Morocco.json'),
    ('NLD', 'Netherlands', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Netherlands.json'),
    ('NZL', 'New_Zealand', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_New_Zealand.json'),
    ('NIC', 'Nicaragua', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Nicaragua.json'),
    ('NGA', 'Nigeria', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Nigeria.json'),
    ('NOR', 'Norway', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Norway.json'),
    ('OMN', 'Oman', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Oman.json'),
    ('PAK', 'Pakistan', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Pakistan.json'),
    ('PAN', 'Panama', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Panama.json'),
    ('PRY', 'Paraguay', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Paraguay.json'),
    ('PER', 'Peru', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Peru.json'),
    ('PHL', 'Philippines', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Philippines.json'),
    ('POL', 'Poland', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Poland.json'),
    ('PRT', 'Portugal', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Portugal.json'),
    ('PRI', 'Puerto_Rico', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Puerto_Rico.json'),
    ('QAT', 'Qatar', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Qatar.json'),
    ('ROU', 'Romania', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Romania.json'),
    ('RUS', 'Russia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Russia.json'),
    ('SMR', 'San_Marino', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_San_Marino.json'),
    ('SAU', 'Saudi_Arabia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Saudi_Arabia.json'),
    ('SRB', 'Serbia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Serbia.json'),
    ('SGP', 'Singapore', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Singapore.json'),
    ('SVK', 'Slovakia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Slovakia.json'),
    ('SVN', 'Slovenia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Slovenia.json'),
    ('ZAF', 'South_Africa', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_South_Africa.json'),
    ('ESP', 'Spain', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Spain.json'),
    ('SWE', 'Sweden', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Sweden.json'),
    ('CHE', 'Switzerland', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Switzerland.json'),
    ('SYR', 'Syria', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Syria.json'),
    ('THA', 'Thailand', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Thailand.json'),
    ('TTO', 'Trinidad_and_Tobago', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Trinidad_and_Tobago.json'),
    ('TUN', 'Tunisia', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Tunisia.json'),
    ('TUR', 'Turkey', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Turkey.json'),
    ('UKR', 'Ukraine', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Ukraine.json'),
    ('ARE', 'United_Arab_Emirates', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_United_Arab_Emirates.json'),
    ('GBR', 'United_Kingdom', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_United_Kingdom.json'),
    ('USA', 'United_States', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_United_States.json'),
    ('URY', 'Uruguay', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Uruguay.json'),
    ('VEN', 'Venezuela', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Venezuela.json'),
    ('VNM', 'Vietnam', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Vietnam.json'),
    ('YEM', 'Yemen', 'https://raw.githubusercontent.com/gaelgael5/calendarium/main/src/calendarium/data/countries/date_Yemen.json');
