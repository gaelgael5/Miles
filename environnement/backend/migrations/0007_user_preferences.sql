-- Préférences personnelles d'une identité : la langue de l'IHM, retenue côté serveur pour
-- qu'on la retrouve d'un navigateur à l'autre. Clé (annuaire, sub) : l'objet « personne »
-- n'existe pas encore, et le rapprochement d'identités ne traverse pas les produits —
-- quelqu'un qui administre les trois y est trois personnes distinctes.
CREATE TABLE user_preferences (
    viewer_directory text NOT NULL,
    viewer_subject text NOT NULL,
    -- NULL : aucun choix, l'IHM suit l'écran de connexion puis en-US.
    language text CHECK (language ~ '^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$'),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (viewer_directory, viewer_subject)
);
