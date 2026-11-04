-- Connecteurs OIDC déclarés à la racine (cadrage : comme le service de sécurité,
-- pas par workspace). Miles accepte plusieurs annuaires : divergence assumée avec la
-- skill oidc-authentication, voir CLAUDE.md.
CREATE TABLE oidc_connectors (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    issuer text NOT NULL CHECK (issuer ~ '^https?://' AND char_length(issuer) <= 500),
    client_id text NOT NULL CHECK (char_length(client_id) BETWEEN 1 AND 200),
    -- Le secret client vit dans le socle des secrets : on n'en garde que le slug.
    -- RESTRICT : un secret encore référencé ne disparaît pas sous le connecteur.
    client_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    scopes text NOT NULL CHECK (scopes ~ '(^| )openid( |$)'),
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

-- Libellé par culture : un seul (en-US) dans ce lot, la déclinaison par culture
-- active vient avec son ticket. La table existe dès maintenant pour ne pas devoir
-- migrer une colonne vers une table à ce moment-là.
CREATE TABLE oidc_connector_labels (
    connector_id text NOT NULL REFERENCES oidc_connectors (id) ON DELETE CASCADE,
    culture text NOT NULL REFERENCES cultures (code),
    label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 200),
    PRIMARY KEY (connector_id, culture)
);

-- Tentatives de connexion en cours : à usage unique, de courte durée. Seule
-- l'empreinte du state est gardée, comme pour les sessions.
CREATE TABLE oidc_login_attempts (
    state_digest bytea PRIMARY KEY,
    connector_id text NOT NULL REFERENCES oidc_connectors (id) ON DELETE CASCADE,
    nonce text NOT NULL,
    code_verifier text NOT NULL,
    expires_at timestamptz NOT NULL
);

CREATE INDEX oidc_login_attempts_expires_idx ON oidc_login_attempts (expires_at);

-- Identités déjà vues, (annuaire, sub) : c'est ce qui rend la suppression d'un
-- connecteur déterministe. RESTRICT : on ne supprime pas un annuaire par lequel des
-- comptes sont arrivés, on le désactive.
CREATE TABLE oidc_identities (
    connector_id text NOT NULL REFERENCES oidc_connectors (id) ON DELETE RESTRICT,
    subject text NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 255),
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    PRIMARY KEY (connector_id, subject)
);

-- Les sessions s'ouvrent aussi par OIDC. `directory` porte le connecteur, et
-- l'identité de la session est le couple (directory, subject), jamais un claim
-- cosmétique. Nom et e-mail ne servent qu'à l'affichage.
ALTER TABLE sessions DROP CONSTRAINT sessions_subject_kind_check;
ALTER TABLE sessions
    ADD COLUMN directory text,
    ADD COLUMN display_name text,
    ADD COLUMN email text,
    ADD CONSTRAINT sessions_subject_kind_check CHECK (subject_kind IN ('local_admin', 'oidc')),
    ADD CONSTRAINT sessions_oidc_has_directory
        CHECK ((subject_kind = 'oidc') = (directory IS NOT NULL));
