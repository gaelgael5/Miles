-- Clés d'API de service (story 0d4e4f75, Gael 22/10/2026) : la gateway du portail les
-- présente pour atteindre la surface MCP. Un compte de service émis par l'administrateur,
-- jamais une clé personnelle ; l'humain mandant arrive à part, par OBO.
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

-- Droits d'une clé, workspace par workspace. Aucune ligne, aucun accès : fail closed.
CREATE TABLE api_key_grants (
    key_id text NOT NULL REFERENCES api_keys (id) ON DELETE CASCADE,
    workspace_id text NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    access text NOT NULL CHECK (access IN ('lecture', 'ecriture')),
    PRIMARY KEY (key_id, workspace_id)
);
