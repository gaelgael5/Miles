-- Service de sécurité racine (Keycloak pour commencer), déclaré depuis l'écran
-- (décision du 20/10/2026). Il authentifie aussi les terminaux : son indisponibilité
-- touche tout le parc. Une seule ligne est admise pour l'instant (contrôle applicatif) :
-- plusieurs services en parallèle n'est pas instruit, mais la table ne le ferme pas.
CREATE TABLE security_services (
    id text PRIMARY KEY CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    kind text NOT NULL CHECK (kind IN ('keycloak')),
    base_url text NOT NULL CHECK (base_url ~ '^https?://' AND char_length(base_url) <= 500),
    realm text NOT NULL CHECK (realm ~ '^[A-Za-z0-9_.-]{1,100}$'),
    client_id text NOT NULL CHECK (char_length(client_id) BETWEEN 1 AND 200),
    client_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    -- Dernier diagnostic : les écrans le montrent sans réinterroger le service.
    last_check_outcome text CHECK (
        last_check_outcome IN ('ok', 'realm_inconnu', 'injoignable', 'refuse')
    ),
    last_check_at timestamptz,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
