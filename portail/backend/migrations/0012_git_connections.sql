-- Connexions git et certificats clients à la racine (Gael, 21/10/2026, stories 7d7dfb41,
-- 738f4b26, 54d6cf1b). L'accès au dépôt ne se déclare plus sur le workspace : il se lit
-- dans la connexion qu'il choisit, et un workspace se crée par son seul nom.

-- Certificat client mTLS : public, gardé ici ; sa clé privée est un secret du socle.
CREATE TABLE client_certificates (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 200),
    cert_pem text NOT NULL CHECK (char_length(cert_pem) <= 16384),
    key_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    -- Lue du certificat à l'enregistrement : un certificat expiré coupe l'accès sans
    -- autre signal, l'écran l'annonce.
    not_after timestamptz NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

-- Connexion à une forge : une adresse (forge ou organisation) et un moyen d'accès —
-- PAT, certificat, ou les deux (arbitrage du 21/10/2026). Une connexion sert plusieurs
-- workspaces ; RESTRICT empêche de retirer ce dont un workspace se sert.
CREATE TABLE git_connections (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 200),
    base_url text NOT NULL CHECK (base_url ~ '^https?://' AND char_length(base_url) <= 300),
    token_secret_slug text REFERENCES secrets (slug) ON DELETE RESTRICT,
    certificate_id text REFERENCES client_certificates (id) ON DELETE RESTRICT,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT git_connections_access_declared
        CHECK (token_secret_slug IS NOT NULL OR certificate_id IS NOT NULL)
);

ALTER TABLE workspaces
    ADD COLUMN git_connection_id text REFERENCES git_connections (id) ON DELETE RESTRICT;

-- Reprise de l'existant, sans perte : chaque workspace déjà créé reçoit une connexion
-- (et, s'il en avait un, un certificat) portant le même identifiant que lui — les deux
-- tables ont leur propre espace de noms. L'adresse de la connexion est l'organisation
-- du dépôt, sous laquelle le dépôt se trouve donc par construction.
INSERT INTO client_certificates
    (id, label, cert_pem, key_secret_slug, not_after, created_at, updated_at)
SELECT id, name, client_cert_pem, client_key_secret_slug, client_cert_not_after, now(), now()
FROM workspaces WHERE client_cert_pem IS NOT NULL;

INSERT INTO git_connections
    (id, label, base_url, token_secret_slug, certificate_id, created_at, updated_at)
SELECT id, name, regexp_replace(repo_url, '^(https?://[^/]+/[^/]+)/.*$', '\1'),
       git_secret_slug, CASE WHEN client_cert_pem IS NOT NULL THEN id END, now(), now()
FROM workspaces;

UPDATE workspaces SET git_connection_id = id;

-- Les secrets ne sont plus tenus par le workspace mais par sa connexion et son
-- certificat : on déplace les déclarations d'usage, sans quoi le socle laisserait
-- supprimer un secret encore servi.
INSERT INTO secret_usages (secret_slug, consumer_kind, consumer_id)
SELECT git_secret_slug, 'git_connection', id FROM workspaces WHERE git_secret_slug IS NOT NULL;
INSERT INTO secret_usages (secret_slug, consumer_kind, consumer_id)
SELECT client_key_secret_slug, 'client_certificate', id
FROM workspaces WHERE client_key_secret_slug IS NOT NULL;
DELETE FROM secret_usages WHERE consumer_kind = 'workspace';

-- Suppression explicite des colonnes reprises ci-dessus : les garder ferait deux sources
-- de vérité pour l'accès au dépôt, qui finiraient par diverger.
ALTER TABLE workspaces
    DROP CONSTRAINT workspaces_access_declared,
    DROP CONSTRAINT workspaces_certificate_complete,
    DROP COLUMN git_secret_slug,
    DROP COLUMN client_cert_pem,
    DROP COLUMN client_key_secret_slug,
    DROP COLUMN client_cert_not_after,
    -- Un workspace se crée par son nom ; le dépôt vient ensuite, avec sa connexion.
    ALTER COLUMN repo_url DROP NOT NULL,
    ADD CONSTRAINT workspaces_repository_complete
        CHECK ((repo_url IS NULL) = (git_connection_id IS NULL));
