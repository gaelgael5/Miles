-- Préférences personnelles d'une identité (ticket 0a52596d, Gael 22/10/2026) : la langue
-- du portail, retenue côté serveur pour qu'on la retrouve d'un navigateur à l'autre.
-- Clé (annuaire, sub), comme branch_views : l'objet « personne » n'existe pas encore.
CREATE TABLE user_preferences (
    viewer_directory text NOT NULL,
    viewer_subject text NOT NULL,
    -- NULL : aucun choix, le portail suit l'écran de connexion puis en-US.
    language text CHECK (language ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (viewer_directory, viewer_subject)
);
