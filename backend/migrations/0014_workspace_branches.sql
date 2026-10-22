-- Branches de travail filles d'un workspace (ticket 6a74c474, Gael 22/10/2026) : on prépare
-- ses modifications dans une branche tirée de la branche de travail de base, qui reste
-- dans workspace_work_branches. La base n'est pas recopiée ici : une seule source pour elle.
CREATE TABLE workspace_branches (
    workspace_id text NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
    -- Dérivée du slug, stockée pour être lisible telle quelle en base et dans le journal.
    branch text NOT NULL CHECK (branch = 'work/' || slug),
    -- Tête de la base au moment de la création : d'où la branche est partie.
    base_commit text NOT NULL CHECK (base_commit ~ '^[0-9a-f]{40,64}$'),
    created_at timestamptz NOT NULL,
    created_by_directory text NOT NULL,
    created_by_subject text NOT NULL,
    PRIMARY KEY (workspace_id, slug)
);
