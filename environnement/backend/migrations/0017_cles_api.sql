-- Clés d'API d'ingestion (story e280c19c, Gael 02/11/2026) : « l'environnement porte une
-- page pour gérer les clés d'api ». Chaque stack authentifie SEULE les systèmes tiers qui
-- déposent des données chez elle. Aucune n'interroge un composant central pour accepter
-- une ingestion : c'est la dépendance que le découpage en trois produits évitait, et un
-- environnement reste alimentable même si le portail est arrêté.
--
-- La clé ne se relit jamais. Ce qui est gardé ici, c'est son empreinte et son début.
CREATE TABLE api_keys (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 120),
    -- Début de la clé, affiché pour la reconnaître ; il ne suffit pas à l'utiliser.
    prefix text NOT NULL UNIQUE,
    -- Empreinte SHA-256 de la clé entière : seule trace gardée. La clé tire 256 bits du
    -- hasard, un hachage lent n'y ajouterait rien ; elle ne se relit jamais.
    digest bytea NOT NULL UNIQUE CHECK (octet_length(digest) = 32),
    created_at timestamptz NOT NULL,
    created_by_directory text NOT NULL,
    created_by_subject text NOT NULL,
    revoked_at timestamptz,
    last_used_at timestamptz
);

-- Ce qu'une clé OUVRE : « une cle ouvre les portes qu'on lui octroie » (Gael, 02/11/2026).
-- Une SOURCE du paramétrage servi, et non un storage : une adresse d'ingestion désigne une
-- entrée de source, et plusieurs sources peuvent alimenter le même storage.
--
-- Aucune ligne, aucun accès : fail closed. Et aucun niveau d'accès — une clé d'ingestion
-- écrit, c'est tout ce qu'elle fait ; recopier le couple lecture/écriture du portail par
-- symétrie aurait créé une lecture que personne n'a instruite.
CREATE TABLE api_key_grants (
    key_id text NOT NULL REFERENCES api_keys (id) ON DELETE CASCADE,
    -- Le NOM de la source, pas une référence : les sources vivent dans git avec la
    -- version servie, jamais en base. Une clé étrangère vers une table de sources
    -- supposerait de les recopier ici, donc d'avoir deux vérités sur ce qui est déclaré.
    -- Conséquence assumée : un octroi peut désigner une source que la version servie ne
    -- déclare plus. Il est donc RELU contre la version à chaque lecture, et l'écran le
    -- signale — on ne réécrit jamais l'octroi tout seul.
    source text NOT NULL CHECK (source ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    PRIMARY KEY (key_id, source)
);
