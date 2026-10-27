-- Sessions du portail. Seule l'empreinte du jeton est stockée : le jeton vit dans
-- le cookie, et une copie de la table ne donne aucune session utilisable.
-- subject_kind distingue le compte d'amorçage local des futures identités OIDC.
CREATE TABLE sessions (
    token_digest bytea PRIMARY KEY,
    subject_kind text NOT NULL CHECK (subject_kind IN ('local_admin')),
    subject text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX sessions_expires_at_idx ON sessions (expires_at);
