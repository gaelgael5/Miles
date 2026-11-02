-- Les dépôts reçus sur les points d'entrée d'ingestion (story 4d4fdcef).
--
-- **Le lot est persisté AVANT toute transformation**, et c'est la règle qui justifie cette
-- table : sans la trace de ce qui est réellement arrivé, un résultat contesté n'est pas
-- reproductible et un incident de transformation n'est pas rejouable. La transformation
-- est le ticket suivant ; elle lira cette table, elle ne la remplacera pas.
CREATE TABLE ingestions (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{32}$'),
    -- La source visée, par son nom dans le paramétrage servi. Pas de clé étrangère : les
    -- sources vivent dans git avec leur version, jamais en base.
    source text NOT NULL CHECK (source ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    -- Le modèle d'entrée qui typait la méthode appelée. Gardé parce qu'une version
    -- suivante peut le changer : sans lui, on ne saurait plus contre quoi ce lot a été
    -- reçu, et c'est précisément ce qu'un résultat contesté demande.
    entry_model text NOT NULL CHECK (entry_model <> ''),
    mode text NOT NULL CHECK (mode IN ('element', 'tableau', 'fichier')),
    -- La version de paramétrage que portait la stack à la réception. C'est elle qui rend
    -- un résultat contesté reproductible (critère 11).
    version_number integer NOT NULL,
    -- L'appelant : la clé, par son identifiant et son libellé. JAMAIS sa valeur.
    key_id text NOT NULL,
    key_label text NOT NULL,
    received_at timestamptz NOT NULL,
    size_bytes integer NOT NULL CHECK (size_bytes >= 0),
    object_count integer NOT NULL CHECK (object_count >= 0),
    -- « recu » : le lot est là, rien n'est transformé. Les états du traitement viendront
    -- avec le ticket qui traite, et avec leur propre migration.
    state text NOT NULL CHECK (state IN ('recu')),
    -- Clé d'idempotence fournie par l'appelant, s'il en fournit une.
    idempotency_key text CHECK (idempotency_key IS NULL OR char_length(idempotency_key) BETWEEN 1 AND 200),
    -- Le lot BRUT, tel qu'il est arrivé.
    raw jsonb NOT NULL
);

-- L'idempotence est portée par l'appelant, et sa portée est SA clé : deux partenaires
-- peuvent employer le même identifiant de lot sans se marcher dessus. Partielle, parce
-- qu'un dépôt sans clé d'idempotence doit pouvoir être rejoué autant de fois qu'on veut
-- (critère 8) — c'est l'écriture qui déduplique, par empreinte, pas la réception.
CREATE UNIQUE INDEX ingestions_idempotence
    ON ingestions (key_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Le journal des appels se lit par source et à l'envers du temps : c'est la seule
-- consultation attendue de cette table (« voir un log des derniers appels », Gael).
CREATE INDEX ingestions_recentes ON ingestions (source, received_at DESC);
