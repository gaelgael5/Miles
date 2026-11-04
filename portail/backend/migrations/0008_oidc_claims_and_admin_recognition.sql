-- Ce que le connecteur déclare en plus de quoi authentifier (ticket 02891f10, décision
-- du 19/10/2026) : les claims à lire, et deux cases qui accordent chacune un pouvoir.
-- DEFAULT false, y compris sur les connecteurs déjà déclarés : aucun pouvoir sans
-- décision explicite d'un administrateur.
ALTER TABLE oidc_connectors
    ADD COLUMN groups_claim text NOT NULL DEFAULT 'groups'
        CHECK (groups_claim ~ '^[A-Za-z0-9_:./-]{1,100}$'),
    ADD COLUMN display_name_claim text NOT NULL DEFAULT 'name'
        CHECK (display_name_claim ~ '^[A-Za-z0-9_:./-]{1,100}$'),
    ADD COLUMN recognize_admin boolean NOT NULL DEFAULT false,
    ADD COLUMN manage_associations boolean NOT NULL DEFAULT false;

-- Administration racine obtenue par reconnaissance de l'e-mail (ticket ad33b114) : elle
-- appartient à la session, jamais à l'identité, et seulement à une session OIDC.
ALTER TABLE sessions
    ADD COLUMN root_admin boolean NOT NULL DEFAULT false,
    ADD CONSTRAINT sessions_root_admin_is_oidc CHECK (NOT root_admin OR subject_kind = 'oidc');
