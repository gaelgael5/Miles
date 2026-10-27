-- Branche que chaque personne regarde dans chaque workspace (ticket 6a74c474, Gael
-- 22/10/2026) : retenue côté serveur, par compte, pour qu'on la retrouve d'un poste à
-- l'autre. L'identité est le couple (annuaire, sub), comme partout ailleurs.
CREATE TABLE branch_views (
    viewer_directory text NOT NULL,
    viewer_subject text NOT NULL,
    workspace_id text NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    slug text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (viewer_directory, viewer_subject, workspace_id)
);
