-- Secrets de l'instance : la valeur vit uniquement ici, chiffrée par MILES_SECRETS_KEY.
-- Pas de colonne « lieu de stockage » : sans coffre ni renvoi vers .env, elle n'aurait
-- rien à dire, et une telle colonne diverge de la valeur au premier correctif
-- (standard globals « Gestion des secrets », §2 bis).
CREATE TABLE secrets (
    -- Le slug est l'identité du secret, immuable : c'est lui que les consommateurs
    -- stockent, et il est lié au chiffré (données associées).
    slug text PRIMARY KEY CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 200),
    secret_type text NOT NULL CHECK (secret_type ~ '^[A-Z][A-Z0-9_]{1,63}$'),
    -- Version de la clé qui a chiffré la valeur : la rotation n'est pas instruite,
    -- mais elle devra savoir quelle clé ouvre quelle ligne.
    key_version smallint NOT NULL CHECK (key_version > 0),
    nonce bytea NOT NULL,
    ciphertext bytea NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX secrets_type_idx ON secrets (secret_type);

-- Qui utilise quel secret. RESTRICT : supprimer un secret encore utilisé est refusé
-- par la base elle-même, même si le code applicatif oubliait de le vérifier.
CREATE TABLE secret_usages (
    secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    consumer_kind text NOT NULL CHECK (consumer_kind ~ '^[a-z][a-z0-9_.-]{0,99}$'),
    consumer_id text NOT NULL CHECK (char_length(consumer_id) BETWEEN 1 AND 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (secret_slug, consumer_kind, consumer_id)
);
