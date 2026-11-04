-- Connecteurs OIDC du module d'enrôlement, déclarés à la racine du produit. Miles accepte
-- plusieurs annuaires : divergence assumée avec la skill oidc-authentication, voir CLAUDE.md.
--
-- Chaque produit déclare SES connecteurs (cadrage, « Renforcé le 26 octobre 2026 ») : le
-- même groupe d'annuaire peut être lu par les trois et y donner trois rôles différents.
-- Forme consolidée : les colonnes de claims sont ici dès la création, le portail les ayant
-- ajoutées par une migration ultérieure qu'il n'y a pas lieu de rejouer.
CREATE TABLE oidc_connectors (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    issuer text NOT NULL CHECK (issuer ~ '^https?://' AND char_length(issuer) <= 500),
    client_id text NOT NULL CHECK (char_length(client_id) BETWEEN 1 AND 200),
    -- Le secret client vit dans le socle des secrets : on n'en garde que le slug.
    -- RESTRICT : un secret encore référencé ne disparaît pas sous le connecteur.
    client_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    scopes text NOT NULL CHECK (scopes ~ '(^| )openid( |$)'),
    active boolean NOT NULL DEFAULT true,
    groups_claim text NOT NULL DEFAULT 'groups'
        CHECK (groups_claim ~ '^[A-Za-z0-9_:./-]{1,100}$'),
    display_name_claim text NOT NULL DEFAULT 'name'
        CHECK (display_name_claim ~ '^[A-Za-z0-9_:./-]{1,100}$'),
    -- DEFAULT false : aucun pouvoir sans décision explicite d'un administrateur.
    recognize_admin boolean NOT NULL DEFAULT false,
    manage_associations boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

-- Libellé par culture active, le libellé en-US étant le repli obligatoire.
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
