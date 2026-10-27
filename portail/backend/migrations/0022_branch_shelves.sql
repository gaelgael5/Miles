-- Rangements (ticket fd1eb7da, Gael 22/10/2026) : quand l'administrateur déverrouille une
-- personne, ses commits non publiés partent sur une branche de la forge,
-- `shelve/<login>/<branche>`, poussée avec SON jeton. Cette table dit qui a quoi de
-- rangé, pour le lui montrer et le fusionner quand elle reprend la main.
CREATE TABLE branch_shelves (
    workspace_id text NOT NULL,
    slug text NOT NULL,
    holder_directory text NOT NULL,
    holder_subject text NOT NULL,
    connection_id text NOT NULL REFERENCES git_connections (id),
    -- Nom de la branche de rangement sur la forge.
    shelf_branch text NOT NULL CHECK (shelf_branch ~ '^shelve/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[a-z0-9][a-z0-9-]{0,39}$'),
    -- Tête rangée, vérifiée sur la forge avant que l'espace soit supprimé.
    shelved_commit text NOT NULL CHECK (shelved_commit ~ '^[0-9a-f]{40,64}$'),
    shelved_at timestamptz NOT NULL,
    shelved_by_directory text NOT NULL,
    shelved_by_subject text NOT NULL,
    -- Un rangement par personne et par branche : un second ne l'écrase jamais.
    PRIMARY KEY (workspace_id, slug, holder_directory, holder_subject),
    FOREIGN KEY (workspace_id, slug) REFERENCES workspace_branches (workspace_id, slug)
        ON DELETE CASCADE
);
