-- Miles serveur d'autorisation OAuth pour sa surface MCP (story 9f09cd8b, Gael 22/10/2026) :
-- claude web s'y connecte avec un client pré-enregistré, public, PKCE. Codes et jetons ne
-- sont gardés que par leur empreinte SHA-256 : ils tirent 256 bits du hasard.

CREATE TABLE oauth_clients (
    id text PRIMARY KEY CHECK (id ~ '^mcl_[0-9a-f]{32}$'),
    label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 120),
    -- Comparées à l'identique, jamais par préfixe : une adresse de retour approchée
    -- enverrait le code à qui sait fabriquer l'adresse voisine.
    redirect_uris text[] NOT NULL CHECK (cardinality(redirect_uris) BETWEEN 1 AND 10),
    created_at timestamptz NOT NULL,
    created_by_directory text NOT NULL,
    created_by_subject text NOT NULL
);

-- Une autorisation : ce qu'une personne a consenti à un client. Les jetons en dépendent.
CREATE TABLE oauth_grants (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    client_id text NOT NULL REFERENCES oauth_clients (id) ON DELETE CASCADE,
    person_directory text NOT NULL,
    person_subject text NOT NULL,
    -- 'local' : le compte d'amorçage ; 'oidc' : une identité d'annuaire. Sert à revérifier
    -- à chaque appel que la personne a toujours les droits qu'elle a délégués.
    person_kind text NOT NULL CHECK (person_kind IN ('local', 'oidc')),
    person_email text,
    display_name text NOT NULL,
    -- {workspace_id: "lecture" | "ecriture"}, choisis au consentement.
    grants jsonb NOT NULL,
    resource text NOT NULL,
    created_at timestamptz NOT NULL,
    revoked_at timestamptz,
    last_used_at timestamptz
);
CREATE INDEX oauth_grants_person ON oauth_grants (person_directory, person_subject);

-- Codes d'autorisation : à usage unique, liés au client, à l'adresse de retour et au défi
-- PKCE. Le consentement y attend l'échange ; l'autorisation naît à l'échange.
CREATE TABLE oauth_codes (
    digest bytea PRIMARY KEY CHECK (octet_length(digest) = 32),
    client_id text NOT NULL REFERENCES oauth_clients (id) ON DELETE CASCADE,
    redirect_uri text NOT NULL,
    code_challenge text NOT NULL,
    person_directory text NOT NULL,
    person_subject text NOT NULL,
    person_kind text NOT NULL CHECK (person_kind IN ('local', 'oidc')),
    person_email text,
    display_name text NOT NULL,
    grants jsonb NOT NULL,
    resource text NOT NULL,
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);

CREATE TABLE oauth_tokens (
    digest bytea PRIMARY KEY CHECK (octet_length(digest) = 32),
    grant_id text NOT NULL REFERENCES oauth_grants (id) ON DELETE CASCADE,
    kind text NOT NULL CHECK (kind IN ('access', 'refresh')),
    expires_at timestamptz NOT NULL,
    -- Un jeton de rafraîchissement ne sert qu'une fois : son rejeu révoque l'autorisation.
    used_at timestamptz,
    created_at timestamptz NOT NULL
);
CREATE INDEX oauth_tokens_grant ON oauth_tokens (grant_id);
