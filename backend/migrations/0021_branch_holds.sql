-- Prise de main d'une branche fille (ticket 9def0adc, Gael 22/10/2026) : qui la tient
-- y modifie seul, en commits locaux à son nom, puis publie avec son propre PAT.
-- « Une personne par branche, une branche par personne » est porté par les deux clés
-- d'unicité : deux demandes simultanées ne peuvent pas aboutir toutes les deux.
CREATE TABLE branch_holds (
    workspace_id text NOT NULL,
    slug text NOT NULL,
    holder_directory text NOT NULL,
    holder_subject text NOT NULL,
    -- Connexion git dont la personne a prêté le PAT à la prise : c'est lui qui publie,
    -- et le retirer est refusé tant que la prise dure (critère 12).
    connection_id text NOT NULL REFERENCES git_connections (id),
    -- Dernière tête publiée : le bail de la prochaine publication. Si la branche a bougé
    -- dans la forge depuis, la publication est refusée au lieu d'écraser (critère 8).
    published_commit text NOT NULL CHECK (published_commit ~ '^[0-9a-f]{40,64}$'),
    taken_at timestamptz NOT NULL,
    PRIMARY KEY (workspace_id, slug),
    UNIQUE (holder_directory, holder_subject),
    -- Seule une branche fille se tient : la racine est en lecture seule (dca0eb0e).
    FOREIGN KEY (workspace_id, slug) REFERENCES workspace_branches (workspace_id, slug)
        ON DELETE CASCADE
);
