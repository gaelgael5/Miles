-- Branche de travail d'un workspace (ticket e2719a5c) : l'espace où l'on fabrique le
-- paramétrage, par opposition aux branches d'environnement, cibles stables.
-- Une seule par workspace (choix du 21/10/2026, réversible) : la clé primaire sur le
-- workspace l'impose, et un second geste ne crée pas d'ambiguïté à l'usage.
CREATE TABLE workspace_work_branches (
    workspace_id text PRIMARY KEY REFERENCES workspaces (id) ON DELETE CASCADE,
    branch text NOT NULL CHECK (branch ~ '^work/[a-z0-9][a-z0-9-]{0,39}$'),
    outcome text NOT NULL CHECK (outcome IN ('initialisee', 'conforme')),
    created_at timestamptz NOT NULL,
    created_by_directory text NOT NULL,
    created_by_subject text NOT NULL
);
