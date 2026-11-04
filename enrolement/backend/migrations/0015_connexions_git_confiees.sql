-- Les connexions git que le module de paramétrage confie à ce module (ticket edcf78bc).
--
-- POURQUOI ELLES SONT ICI ET PAS AILLEURS. La décision de sécurité qui porte le ticket :
-- « le secret s'arrête au module d'enrôlement ». Un module d'environnement ne reçoit
-- jamais de credential git — il lira git par le relais —, et deux propriétés en découlent :
-- un environnement compromis ne livre pas l'accès au dépôt, et un environnement révoqué
-- perd son accès à git sans qu'on révoque quoi que ce soit chez la forge.
--
-- POURQUOI LE CREDENTIAL EST DANS CETTE TABLE ET NON DANS `secrets`. Le critère 3 demande
-- de reprendre ce qu'on a fait pour les secrets du workspace : c'est le CHIFFREMENT qui est
-- repris — même AES-GCM, même MILES_SECRETS_KEY, mêmes données associées liant le chiffré à
-- sa ligne. Ce qui n'est pas repris, c'est la TABLE, et pour trois raisons : un credential
-- confié n'est pas un secret de l'instance, personne ici n'a le droit de le remplacer à la
-- main — l'écran des secrets le permettrait, et ce serait exactement la ressaisie que le
-- ticket supprime —, et sa durée de vie est celle de l'appariement, alors que `secrets`
-- refuse justement la suppression d'un secret encore utilisé.
--
-- POURQUOI L'ESPÈCE EST RECOPIÉE DANS CES TABLES. C'est le seul moyen d'exprimer en DDL
-- « une connexion git confiée ne peut appartenir qu'à un module de paramétrage » : une
-- clé étrangère composée vers (base_url, species) plus un CHECK sur la valeur. Le critère
-- 10 du ticket exige que ça tienne au niveau des données — « c'est la facilité qui se
-- présentera le jour où le relais sera lent » —, et une colonne recopiée que la base tient
-- d'accord vaut mieux qu'une garde applicative qu'on peut oublier d'appeler.

-- Exigée par la clé étrangère composée ci-dessous : PostgreSQL veut une unicité déclarée
-- sur les colonnes référencées, et `base_url` seule est la clé primaire.
ALTER TABLE environment_peer
    ADD CONSTRAINT environment_peer_base_url_species_unique UNIQUE (base_url, species);

-- La dernière transmission reçue. Une table et non une colonne de `environment_peer` :
-- cette révision n'a aucun sens pour un environnement, et une colonne toujours nulle pour
-- l'espèce la plus nombreuse ferait lire le modèle de travers. Même raison que
-- l'environnement assigné, sorti du pair chez le module d'environnement le 29/10/2026.
CREATE TABLE confided_git_state (
    peer_base_url text PRIMARY KEY,
    species text NOT NULL CHECK (species = 'parametrage'),
    -- Strictement croissante, allouée par le module de paramétrage quand il lit son état.
    -- Elle fait refuser une transmission ancienne arrivée en retard : sans elle, deux
    -- administrateurs qui changent deux connexions en même temps peuvent laisser ici la
    -- plus vieille des deux photos, et rien ne le dirait.
    revision bigint NOT NULL CHECK (revision >= 1),
    received_at timestamptz NOT NULL,
    -- ON DELETE CASCADE, et c'est le critère 8 : révoquer le module de paramétrage
    -- DÉTRUIT ce qui lui était confié. Pas de marque « inactif » — une ligne inactive est
    -- une ligne qui porte encore le secret, et un jour quelqu'un la relira.
    FOREIGN KEY (peer_base_url, species)
        REFERENCES environment_peer (base_url, species) ON DELETE CASCADE
);

CREATE TABLE confided_git_connection (
    peer_base_url text NOT NULL,
    species text NOT NULL CHECK (species = 'parametrage'),
    -- L'identifiant que la connexion porte chez le module de paramétrage. On le reprend
    -- tel quel : c'est par lui qu'un humain fait le lien entre les deux écrans, et s'en
    -- forger un autre ici rendrait ce lien indémontrable.
    id text NOT NULL CHECK (id ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 200 AND label !~ '[[:cntrl:]]'),
    -- La forge, ou une organisation de la forge. Bornée et de forme vérifiée, mais SANS
    -- liste de forges admises : quelles forges on accepte est la règle du module de
    -- paramétrage, où un humain saisit l'adresse. Ici on borne ce qu'on écrit, on ne
    -- re-décide pas ce qu'il a accepté — sinon le jour où il admettra une forge de plus,
    -- la transmission serait refusée par une base qui n'avait pas à en juger.
    base_url text NOT NULL
        CHECK (base_url ~ '^https?://[A-Za-z0-9.-]{1,253}(:[0-9]{2,5})?(/[A-Za-z0-9_.-]{1,100})?$'),
    -- Le credential, chiffré. Les trois colonnes sont celles de `secrets` : version de
    -- clé, nonce, chiffré. La version permet de refuser proprement un chiffré d'une autre
    -- clé au lieu de servir une valeur approchée.
    key_version integer NOT NULL,
    nonce bytea NOT NULL,
    ciphertext bytea NOT NULL,
    -- Quand cette connexion a été confiée pour la première fois, et quand son credential a
    -- changé pour la dernière. Nul tant qu'il n'a jamais été remplacé, et c'est l'état
    -- normal : le renouvellement est le cas d'usage principal du ticket, donc la date à
    -- laquelle il a eu lieu est ce qu'on viendra lire quand une lecture de git échouera.
    confided_at timestamptz NOT NULL,
    renewed_at timestamptz,
    PRIMARY KEY (peer_base_url, id),
    FOREIGN KEY (peer_base_url, species)
        REFERENCES environment_peer (base_url, species) ON DELETE CASCADE
);

-- Les workspaces qui se servent d'une connexion, et le dépôt que chacun travaille. Le
-- dépôt est ici parce qu'il est au workspace : une connexion porte la forge, chaque
-- workspace y choisit son dépôt. UN workspace relève d'UNE connexion — c'est le modèle du
-- module de paramétrage, et la clé primaire le dit.
CREATE TABLE confided_git_workspace (
    peer_base_url text NOT NULL,
    id text NOT NULL CHECK (char_length(id) BETWEEN 1 AND 200 AND id !~ '[[:cntrl:]]'),
    connection_id text NOT NULL,
    -- NUL pour un workspace dont le dépôt n'est pas encore configuré. Il est transmis
    -- quand même : l'omettre ferait diverger en silence cette liste de celle qu'affiche le
    -- module de paramétrage, et personne ne saurait lequel des deux a raison.
    repo_url text
        CHECK (repo_url IS NULL OR repo_url ~
            '^https?://[A-Za-z0-9.-]{1,253}(:[0-9]{2,5})?(/[A-Za-z0-9_.-]{1,100}){1,3}$'),
    PRIMARY KEY (peer_base_url, id),
    FOREIGN KEY (peer_base_url, connection_id)
        REFERENCES confided_git_connection (peer_base_url, id) ON DELETE CASCADE
);
