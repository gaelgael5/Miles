-- Appariement d'un module d'environnement au module d'enrôlement (ticket 6a0daab6) :
-- l'identité de ce module, les demandes en attente, et les environnements appariés.
--
-- POURQUOI CES TROIS TABLES SONT EN BASE, et non dans ce que le calcul de la stack
-- engendre : l'appariement doit survivre à un redéploiement. Si les clés vivaient dans le
-- contenu calculé, un redéploiement casserait tous les appariements, et il faudrait
-- réapparier chaque environnement à la main puis réaffecter ses devices. La base est ce
-- qui persiste (volume), la stack est ce qui est recalculé.

-- Identité de CE module. Même forme que celle du module d'environnement, et ce n'est pas
-- une recopie malheureuse : les requêtes sont écrites une seule fois, au socle
-- (`miles_socle.signing.identity_store`), et c'est la TABLE qui reste au produit — le
-- socle ne porte aucune migration, le schéma de chaque produit étant relu produit par
-- produit (décision du 27/10/2026).
CREATE TABLE module_identity (
    -- Une SEULE ligne, garantie par le modèle et non par le code : un module a une
    -- identité, pas une collection. Deux lignes voudraient dire deux identités pour une
    -- stack, et plus aucune réponse unique à « qui a signé cet appel ».
    id text PRIMARY KEY CHECK (id = 'self'),
    public_key text NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]{43}$'),
    -- La clé privée n'est JAMAIS ici : seulement le renvoi vers sa ligne de la table des
    -- secrets, où elle est chiffrée par MILES_SECRETS_KEY.
    private_key_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    created_at timestamptz NOT NULL
);

-- Une demande d'appariement en attente du geste humain. Elle porte le secret dont le code
-- TOTP est dérivé, et ce secret est en BASE — jamais en mémoire de processus. L'humain lit
-- le code sur une instance et le colle vers une autre : sans état partagé, l'appariement
-- échouerait par intermittence et le diagnostic partirait sur l'horloge.
CREATE TABLE pairing_request (
    -- L'origine de l'environnement EST la clé : « même URL qui frappe deux fois sans avoir
    -- été acceptée » donne UNE demande dont le secret est renouvelé, pas deux demandes
    -- concurrentes dont l'humain ne saurait laquelle accepter.
    base_url text PRIMARY KEY CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    -- La clé publique que l'environnement dépose. Elle ne vaut rien tant que l'humain n'a
    -- pas accepté : enregistrer n'authentifie pas. Ce qu'elle prouve déjà, c'est la
    -- POSSESSION de la clé privée correspondante, la demande étant signée par elle.
    public_key text NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]{43}$'),
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    -- Le secret TOTP, chiffré exactement comme les secrets de l'instance. Il n'a pas de
    -- ligne dans `secrets` : il vit le temps d'une demande, et une ligne par tentative
    -- d'appariement encombrerait l'écran des secrets de valeurs mortes. Les données
    -- associées du chiffrement sont le `base_url` : recopié sur une autre demande, le
    -- chiffré ne s'ouvre plus.
    key_version smallint NOT NULL CHECK (key_version > 0),
    nonce bytea NOT NULL,
    ciphertext bytea NOT NULL,
    created_at timestamptz NOT NULL,
    -- Une demande jamais traitée expire, et son secret disparaît avec sa ligne. Sans
    -- échéance, un code resterait valide indéfiniment sur un écran que plus personne ne
    -- regarde.
    expires_at timestamptz NOT NULL
);

CREATE INDEX pairing_request_expires_idx ON pairing_request (expires_at);

-- Les environnements appariés. UN module d'enrôlement apparie N environnements : c'est
-- toute sa raison d'être, et la réciproque est fausse — un environnement n'est apparié
-- qu'à un seul module d'enrôlement, contrainte portée par la base de l'ENVIRONNEMENT.
CREATE TABLE environment_peer (
    -- L'origine est la clé : c'est elle que l'appel signé déclare, et c'est par elle qu'on
    -- retrouve la clé publique avec laquelle le vérifier. Deux lignes pour la même origine
    -- rendraient « avec quelle clé vérifier » sans réponse unique.
    base_url text PRIMARY KEY CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    public_key text NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]{43}$'),
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    -- Conservé au ré-appariement : il date l'appariement initial, qui reste un fait même
    -- après rotation des clés. `updated_at` dit, lui, quand la clé courante est arrivée.
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
