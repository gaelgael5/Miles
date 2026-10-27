-- Un workspace = une application métier (cadrage), avec son dépôt git et sa référence
-- au service de sécurité racine.
CREATE TABLE workspaces (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
    -- Adresse normalisée (casse comprise) : UNIQUE interdit qu'un même dépôt serve deux
    -- workspaces, qui partageraient sinon leurs commits d'environnement (critère 15).
    repo_url text NOT NULL UNIQUE CHECK (repo_url ~ '^https?://' AND char_length(repo_url) <= 300),
    git_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    -- Le workspace référence le service, il ne le possède pas : RESTRICT protège le
    -- service, et supprimer un workspace n'y touchera pas.
    security_service_id text REFERENCES security_services (id) ON DELETE RESTRICT,
    last_check jsonb,
    last_check_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
