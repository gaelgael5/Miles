-- Certificat client mTLS d'accès au dépôt (ticket 63ecbec8). L'accès se déclare par un
-- jeton, un certificat, ou les deux — au moins l'un des deux (décision du 16/10/2026).
-- Le certificat est public et se garde ici ; sa clé privée est un secret du socle.
ALTER TABLE workspaces
    ALTER COLUMN git_secret_slug DROP NOT NULL,
    ADD COLUMN client_cert_pem text CHECK (char_length(client_cert_pem) <= 16384),
    ADD COLUMN client_key_secret_slug text REFERENCES secrets (slug) ON DELETE RESTRICT,
    -- L'échéance se lit du certificat à l'enregistrement : un dépôt devenu inaccessible
    -- parce qu'un certificat a expiré est un incident silencieux, la fiche l'annonce.
    ADD COLUMN client_cert_not_after timestamptz,
    ADD CONSTRAINT workspaces_access_declared
        CHECK (git_secret_slug IS NOT NULL OR client_cert_pem IS NOT NULL),
    ADD CONSTRAINT workspaces_certificate_complete CHECK (
        (client_cert_pem IS NULL) = (client_key_secret_slug IS NULL)
        AND (client_cert_pem IS NULL) = (client_cert_not_after IS NULL)
    );
