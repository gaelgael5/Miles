-- Identité du module d'environnement : la paire de clés qu'il détient, et le module
-- d'enrôlement auquel il est apparié (ticket 8c95ecc7).
--
-- POURQUOI CES DEUX TABLES SONT ICI, et non dans ce que le calcul de la stack engendre :
-- l'identité de l'environnement doit survivre à un redéploiement de sa stack. Si la clé
-- privée vivait dans le contenu calculé, un redéploiement casserait l'appariement, et il
-- faudrait réapparier à la main puis réaffecter les devices. La base est ce qui persiste
-- (volume), la stack est ce qui est recalculé : l'identité vit donc du côté de la base.

CREATE TABLE module_identity (
    -- Une SEULE ligne, garantie par le modèle et non par le code : un module a une
    -- identité, pas une collection. Deux lignes voudraient dire deux identités pour une
    -- stack, et plus aucune réponse unique à « qui a signé cet appel ».
    id text PRIMARY KEY CHECK (id = 'self'),
    -- Clé publique en base64url sans rembourrage : 43 caractères, la forme sous laquelle
    -- elle voyage vers le module d'enrôlement.
    public_key text NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]{43}$'),
    -- La clé privée n'est JAMAIS ici : seulement le renvoi vers sa ligne de la table des
    -- secrets, où elle est chiffrée par MILES_SECRETS_KEY. RESTRICT est le dernier mot de
    -- la base ; `secret_usages` porte en plus l'usage déclaré, qui fait refuser la
    -- suppression PROPREMENT (409) au lieu de la laisser buter sur cette contrainte (500).
    private_key_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    -- Écrit alors qu'une seule valeur est admise : le jour où une seconde signature
    -- existe, les lignes déjà écrites disent laquelle les a produites. Sans la colonne,
    -- il faudrait le deviner.
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    created_at timestamptz NOT NULL
);

-- Le module d'enrôlement apparié. Une seule ligne, par le modèle : « un environnement
-- n'est apparié qu'à un seul module d'enrôlement » (Gael, 26/10/2026), parce que ce
-- module est l'autorité UNIQUE sur l'affectation des devices de cet environnement. Deux
-- autorités qui s'ignorent, et « à qui appartient ce device » n'aurait plus de réponse.
-- La réciproque est fausse et doit le rester : un module d'enrôlement apparie N
-- environnements, c'est toute sa raison d'être.
CREATE TABLE enrolment_peer (
    id text PRIMARY KEY CHECK (id = 'self'),
    -- Origine http(s) sans chemin : c'est elle qui entre dans la chaîne signée de chaque
    -- appel, dans les deux sens. Un chemin la rendrait ambiguë.
    base_url text NOT NULL CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    public_key text NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]{43}$'),
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);
