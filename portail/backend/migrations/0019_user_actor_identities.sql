-- Identité d'acteur (story 52ac5782, contrat globals OBO v6) : le GUID qu'une personne pose
-- dans son profil, le même que dans son profil du portail. Il ne sert qu'à la retrouver
-- depuis l'en-tête signé `x-portal-actor` ; l'identité reste (annuaire, sub).
CREATE TABLE user_actor_identities (
    viewer_directory text NOT NULL,
    viewer_subject text NOT NULL,
    -- Unique : un même GUID désignant deux personnes, l'attribution serait au hasard.
    actor text NOT NULL UNIQUE CHECK (actor ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    -- Nom et e-mail retenus à la pose, pour signer un commit quand la personne n'a pas
    -- d'identité git personnelle : la session n'est pas là quand l'agent écrit.
    display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 200),
    email text,
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (viewer_directory, viewer_subject)
);
