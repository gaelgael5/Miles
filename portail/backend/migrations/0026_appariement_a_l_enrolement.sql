-- L'identité de ce module et son appariement au module d'enrôlement (ticket ba44914b).
--
-- POURQUOI LE PORTAIL S'APPARIE. Les connexions git sont saisies ici, workspace par
-- workspace, et elles le seront bientôt UNE SEULE FOIS au module d'enrôlement, qui les
-- servira (ticket edcf78bc). Pour qu'il les lui confie, il faut d'abord que les deux se
-- reconnaissent — c'est ce que pose cette migration, et rien de plus : aucune connexion ne
-- voyage encore.
--
-- POURQUOI TROIS TABLES ET NON UNE DE PLUS À L'EXISTANT. C'est le MÊME mécanisme que celui
-- du module d'environnement, dont le code est au socle depuis le 29/10/2026
-- (`miles_socle.pairing`) : les requêtes sont écrites une fois et servent les deux
-- demandeurs. Ce qui reste au produit, ce sont les tables — le socle ne porte aucune
-- migration (décision du 27/10/2026), et l'écart entre les schémas est tenu par la revue
-- humaine plus un test du produit qui rougit si l'une manque.
--
-- Les commentaires de forme sont donc volontairement COURTS ici : la raison de chaque
-- colonne est écrite une fois, dans les migrations 8 à 13 du module d'environnement, et la
-- recopier en entier donnerait deux textes à tenir d'accord. Ce qui est dit ici est ce qui
-- est propre au portail.
--
-- POURQUOI EN BASE, et non dans ce que le calcul de la stack engendre : l'appariement doit
-- survivre à un redéploiement. Une clé privée qui vivrait dans le contenu calculé serait
-- perdue au redéploiement suivant, et il faudrait réapparier à la main — puis se faire
-- reconfier tout ce qui l'avait été.

CREATE TABLE module_identity (
    -- Une SEULE ligne, garantie par le modèle : un module a une identité, pas une
    -- collection. Deux lignes, et plus aucune réponse unique à « qui a signé cet appel ».
    id text PRIMARY KEY CHECK (id = 'self'),
    public_key text NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]{43}$'),
    -- La clé privée n'est JAMAIS ici : seulement le renvoi vers sa ligne de `secrets`, où
    -- elle est chiffrée par MILES_SECRETS_KEY. RESTRICT est le dernier mot de la base ;
    -- `secret_usages` porte en plus l'usage déclaré, qui fait refuser la suppression
    -- proprement (409) au lieu de la laisser buter ici (500).
    private_key_secret_slug text NOT NULL REFERENCES secrets (slug) ON DELETE RESTRICT,
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    created_at timestamptz NOT NULL
);

-- La demande d'appariement en cours. Une table et non un état en mémoire : l'appariement
-- se fait en deux gestes séparés par un aller-retour humain, et le portail tourne en
-- plusieurs instances derrière un équilibreur — un état en mémoire ferait échouer
-- l'appariement par intermittence, et le diagnostic partirait sur le code.
CREATE TABLE pairing_attempt (
    id text PRIMARY KEY CHECK (id = 'self'),
    base_url text NOT NULL CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    created_at timestamptz NOT NULL,
    -- Le nom sous lequel CE module se présente, saisi par un administrateur. Il
    -- n'identifie rien : il sert à ce qu'un humain, à l'autre bout, reconnaisse la demande
    -- qu'il accepte.
    name text CHECK (name IS NULL OR (char_length(name) BETWEEN 1 AND 80
        AND name !~ '[[:cntrl:]]')),
    -- L'échéance annoncée par le pair en accusant la demande : c'est elle qui permet de
    -- distinguer REFUSÉE d'EXPIRÉE, le pair ne disant jamais que « inconnue ».
    expires_at timestamptz
);

-- Le module d'enrôlement apparié. UNE SEULE ligne, par le modèle, et la raison est propre
-- au portail : c'est l'enrôlement qui lui confiera les connexions git, et deux enrôlements
-- appariés voudraient dire deux autorités sur les mêmes secrets — donc plus aucune réponse
-- unique à « qui nous a confié celle-ci ». La réciproque est fausse et doit le rester : un
-- module d'enrôlement apparie N environnements et UN module de paramétrage.
CREATE TABLE enrolment_peer (
    id text PRIMARY KEY CHECK (id = 'self'),
    -- Son IDENTITÉ : l'origine qu'il déclare, celle qui entre dans la chaîne signée de ses
    -- appels vers nous, et la seule contre laquelle on vérifie un appel entrant.
    base_url text NOT NULL CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    public_key text NOT NULL CHECK (public_key ~ '^[A-Za-z0-9_-]{43}$'),
    algorithm text NOT NULL CHECK (algorithm = 'ed25519'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    -- Le nom que CE module a déclaré en s'appariant, pas celui du pair, qui n'en déclare
    -- aucun : il permet de retrouver sa demande dans la liste de l'autre bout.
    declared_name text CHECK (declared_name IS NULL
        OR (char_length(declared_name) BETWEEN 1 AND 80 AND declared_name !~ '[[:cntrl:]]')),
    -- L'ADRESSE où on le joint, distincte de son identité : la chaîne canonique signée
    -- porte l'origine de l'ÉMETTEUR, jamais l'hôte appelé, donc composer ailleurs ne change
    -- rien à ce que le pair vérifie. NOT NULL dès la création — la table est neuve, il n'y
    -- a aucune ligne à remplir d'abord, et un repli calculé dans le code serait
    -- indiscernable d'un bug le jour où la valeur manquerait pour une autre raison.
    contact_url text NOT NULL CHECK (contact_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    -- Quand l'avis de révocation a été REÇU, avec NOTRE horloge. Nul tant qu'il n'est pas
    -- venu, et c'est l'état normal. L'avis n'est pas cru sur parole : l'écran ne nomme la
    -- révocation que si les appels nous sont AUSSI refusés — l'avis dit la cause, l'appel
    -- dit le fait.
    revoked_at timestamptz
);
