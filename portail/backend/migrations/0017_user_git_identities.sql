-- Identité git personnelle (ticket 033e5ff3, Gael 22/10/2026) : un PAT par personne et par
-- connexion git, sous lequel elle modifiera le paramétrage en son nom. Chiffré comme les
-- secrets de l'instance, jamais restitué ; clé (annuaire, sub) comme les préférences.
CREATE TABLE user_git_identities (
    viewer_directory text NOT NULL,
    viewer_subject text NOT NULL,
    connection_id text NOT NULL REFERENCES git_connections (id) ON DELETE CASCADE,
    key_version integer NOT NULL,
    nonce bytea NOT NULL,
    ciphertext bytea NOT NULL,
    -- Lus sur le compte de la forge à la vérification : l'auteur des commits.
    login text NOT NULL,
    name text NOT NULL,
    email text NOT NULL,
    email_origin text NOT NULL CHECK (email_origin IN ('public', 'emails', 'noreply')),
    -- Droit d'écriture constaté sur les dépôts de la connexion, à la vérification.
    repositories jsonb NOT NULL,
    verified_at timestamptz NOT NULL,
    PRIMARY KEY (viewer_directory, viewer_subject, connection_id)
);
