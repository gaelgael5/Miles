-- Sessions du module d'enrôlement. Seule l'empreinte du jeton est stockée : le jeton vit
-- dans le cookie, et une copie de la table ne donne aucune session utilisable.
--
-- Étanchéité (décision de Gael du 27/10/2026) : cette table est PROPRE à ce produit, et
-- son secret de session n'est partagé avec aucun autre. Une session ouverte sur le portail
-- n'y a donc pas d'empreinte et vaut refus. Ce qui se partage entre produits, c'est
-- l'annuaire OIDC : la reconnexion y est silencieuse parce que c'est le fournisseur qui
-- reconnaît la personne, jamais notre cookie.
--
-- Forme consolidée : le portail y est arrivé par trois migrations successives, cette base
-- part de zéro et n'a aucun historique à préserver.
CREATE TABLE sessions (
    token_digest bytea PRIMARY KEY,
    -- `directory` porte le connecteur OIDC, et l'identité de la session est le couple
    -- (directory, subject), jamais un claim cosmétique. Nom et e-mail sont d'affichage.
    subject_kind text NOT NULL CHECK (subject_kind IN ('local_admin', 'oidc')),
    subject text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    directory text,
    display_name text,
    email text,
    -- Administration racine obtenue par reconnaissance de l'e-mail : elle appartient à la
    -- session, jamais à l'identité, et seulement à une session OIDC.
    root_admin boolean NOT NULL DEFAULT false,
    CONSTRAINT sessions_oidc_has_directory
        CHECK ((subject_kind = 'oidc') = (directory IS NOT NULL)),
    CONSTRAINT sessions_root_admin_is_oidc CHECK (NOT root_admin OR subject_kind = 'oidc')
);

CREATE INDEX sessions_expires_at_idx ON sessions (expires_at);
