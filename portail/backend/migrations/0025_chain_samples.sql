-- Échantillon source de test d'une chaîne de transformations (Gael, 24/10/2026).
--
-- EN BASE, et non dans git : c'est un cas d'essai, pas du paramétrage. Il ne part donc
-- pas dans le dépôt du client — où rien de confidentiel ne doit atterrir — mais il
-- survit au rechargement et se partage entre les personnes de l'instance.
-- Revers assumé, et dit à l'écran : il ne suit ni une publication, ni un retour arrière.
--
-- Une ligne par (workspace, branche, chaîne) : la branche fait partie de la clé parce
-- qu'une chaîne y évolue, et qu'un échantillon valable sur la branche de travail ne l'est
-- pas forcément sur une autre. Aucune clé étrangère vers la branche : la racine n'est pas
-- dans workspace_branches, et on doit pouvoir y éprouver une chaîne en lecture.
CREATE TABLE chain_samples (
    workspace_id text NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    branch_slug text NOT NULL CHECK (branch_slug ~ '^[a-z0-9][a-z0-9-]{0,39}$'),
    chain_slug text NOT NULL CHECK (chain_slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    -- Borné comme les documents de modèle : un échantillon se colle, il ne se téléverse
    -- pas sans limite.
    sample text NOT NULL CHECK (length(sample) <= 65536),
    updated_at timestamptz NOT NULL,
    updated_by_directory text NOT NULL,
    updated_by_subject text NOT NULL,
    PRIMARY KEY (workspace_id, branch_slug, chain_slug)
);
