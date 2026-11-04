-- Le mode gros fichier : le dépôt posé sur disque, sa file, et son aire de préparation
-- (story 0f14adbd).
--
-- Trois choses entrent ici, et chacune parce qu'un critère l'exige :
--
-- 1. **Un dépôt de mode `fichier` n'a pas de lot BRUT** : son contenu est sur le disque de
--    la stack, pas dans la base. `raw` devient donc nullable, et deux contrôles disent
--    l'invariant plutôt que de le laisser à la bonne tenue du code — les deux colonnes
--    s'excluent selon le mode.
-- 2. **L'import est ASYNCHRONE** : le contrat publié promet au mode `fichier` un
--    « acquittement de prise en charge », pas un compte-rendu. D'où des états de file et
--    d'exécution, et les instants qui permettent de comparer la durée de la transaction
--    d'écriture à la durée totale de l'import (critère 9).
-- 3. **Le parsing et la transformation ont lieu HORS transaction** (interdit explicite du
--    ticket : autovacuum, et le bloat sur la table que l'import malmène). Les items
--    transformés attendent donc dans une aire de préparation, et une seule transaction
--    courte confronte celle-ci à la table du storage.

-- Le storage visé, recopié de la déclaration de la source au moment du dépôt. Pas de clé
-- étrangère : les storages vivent dans git avec leur version, jamais en base. Nullable,
-- parce que les dépôts déjà reçus n'en portent pas — réconciliation additive.
--
-- POURQUOI LE RECOPIER alors que la source le donne : c'est lui, et non la source, qui
-- sérialise les imports (critère 12). Deux sources peuvent alimenter le même storage, et
-- leurs imports ne doivent pas s'y croiser ; aller le relire dans l'arbre servi pour
-- choisir qui passe aurait fait dépendre la file d'un fichier qui change.
ALTER TABLE ingestions ADD COLUMN storage text;

-- Le fichier déposé, par son nom sur le disque de la stack — l'identifiant de l'ingestion.
-- Le chemin complet n'est PAS en base : il dépend du volume monté, qui est une
-- configuration de déploiement, et une base restaurée ailleurs ne doit pas désigner un
-- répertoire qui n'existe plus là-bas.
-- La TAILLE du fichier n'a pas sa colonne : c'est `size_bytes`, qui dit déjà « ce qui a
-- été déposé » pour les trois modes. Deux colonnes auraient fini par ne plus dire la même
-- chose, et c'est celle qui survit à la purge qu'on veut lire.
ALTER TABLE ingestions ADD COLUMN file_name text;
-- L'instant où le fichier a été purgé. L'HISTORIQUE RESTE, et c'est le critère 16 : la
-- ligne porte alors la mention que le fichier n'est plus disponible, au lieu de disparaître
-- avec lui — on doit pouvoir lire des mois plus tard qu'un import a eu lieu.
ALTER TABLE ingestions ADD COLUMN file_purged_at timestamptz;

-- `size_bytes` passait en `integer` : un fichier de plus de deux gigaoctets l'aurait fait
-- déborder, et le plafond de taille est paramétrable sans limite écrite ici.
ALTER TABLE ingestions ALTER COLUMN size_bytes TYPE bigint;

-- Les métadonnées du document, hors du tableau d'items : lues par la PREMIÈRE passe, qui
-- existe parce que JSON ne garantit pas que les clés précèdent le tableau (critère 6).
ALTER TABLE ingestions ADD COLUMN metadata jsonb;

-- Le nombre d'items lus avant un incident de lecture. C'est ce que les critères 7 et 8
-- exigent de dire : « échoué après 12 400 items » est exploitable, « échoué » ne l'est pas.
ALTER TABLE ingestions ADD COLUMN items_read integer CHECK (items_read IS NULL OR items_read >= 0);

-- Les trois instants de l'import. `apply_started_at` est celui qui porte le critère 9 :
-- la transaction d'écriture doit être COURTE devant la durée totale, et cela se compare.
ALTER TABLE ingestions ADD COLUMN started_at timestamptz;
ALTER TABLE ingestions ADD COLUMN apply_started_at timestamptz;
ALTER TABLE ingestions ADD COLUMN finished_at timestamptz;

-- Le lot brut n'existe que pour les modes qui reçoivent des objets dans l'appel.
ALTER TABLE ingestions ALTER COLUMN raw DROP NOT NULL;

-- LES DEUX INVARIANTS DU MODE, écrits en contraintes et non laissés au code : c'est la
-- seule façon qu'une ligne incohérente — un dépôt de fichier sans fichier, un lot
-- d'objets sans objets — ne puisse pas exister du tout.
ALTER TABLE ingestions ADD CONSTRAINT ingestions_lot_ou_fichier
    CHECK ((mode = 'fichier') = (raw IS NULL));
ALTER TABLE ingestions ADD CONSTRAINT ingestions_fichier_nomme
    CHECK ((mode = 'fichier') = (file_name IS NOT NULL));

-- Les états. La contrainte est CHERCHÉE et non nommée, pour la même raison que dans la
-- migration 0021 : PostgreSQL auto-nomme et suffixe en silence, et le nom présumé ferait
-- échouer la migration sur une base ancienne.
DO $$
DECLARE
    nom text;
BEGIN
    SELECT c.conname INTO nom
    FROM pg_constraint c
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
    WHERE c.conrelid = 'ingestions'::regclass
      AND c.contype = 'c'
      AND a.attname = 'state';
    IF nom IS NULL THEN
        RAISE EXCEPTION 'aucune contrainte de controle sur ingestions.state : schema inattendu';
    END IF;
    EXECUTE format('ALTER TABLE ingestions DROP CONSTRAINT %I', nom);
END $$;

-- « en_file » : le fichier est sur le disque, rien n'est lu. « en_cours » : un import le
-- traite. « incomplet » : le document s'est interrompu et la transaction n'était PAS
-- unifiée, donc les items valides lus avant l'incident sont écrits (critère 8) — c'est
-- l'état que le balayage refuse. « echec » : rien n'a été écrit.
ALTER TABLE ingestions ADD CONSTRAINT ingestions_etat
    CHECK (state IN ('recu', 'traite', 'rejete', 'en_file', 'en_cours', 'incomplet', 'echec'));

-- Pourquoi un import a échoué ou s'est arrêté incomplet, par un code stable. En colonne
-- et non seulement dans le compte-rendu : c'est ce que l'écran d'historique montre, et un
-- import en échec n'a pas forcément de compte-rendu à montrer.
ALTER TABLE ingestions ADD COLUMN failure_code text;
ALTER TABLE ingestions ADD COLUMN failure_detail text;

-- La file des imports, lue par storage et dans l'ordre d'arrivée. Index PARTIEL : la table
-- porte tout l'historique des dépôts, et la file n'en est qu'une poignée de lignes.
CREATE INDEX ingestions_en_file ON ingestions (storage, received_at)
    WHERE state IN ('en_file', 'en_cours');

-- Les fichiers encore conservés, du plus ancien au plus récent : c'est l'ordre de la purge
-- (par ancienneté d'abord, critère 17).
CREATE INDEX ingestions_fichiers_conserves ON ingestions (received_at)
    WHERE file_name IS NOT NULL AND file_purged_at IS NULL;

-- L'AIRE DE PRÉPARATION d'un import de fichier.
--
-- Elle existe pour tenir l'interdit du ticket : ne pas garder la transaction d'écriture
-- ouverte pendant le parsing et la transformation. Sur un gros fichier, le temps n'est pas
-- dans l'écriture mais dans l'évaluation du template item par item ; une transaction
-- ouverte plusieurs minutes empêche autovacuum de nettoyer les versions mortes de la table
-- que l'import malmène, et sur un import quotidien le bloat s'installe. L'opération longue
-- cesse donc d'être une transaction et devient une PRÉPARATION ; la partie atomique dure
-- quelques secondes au lieu de quelques minutes, et l'abandon d'une préparation ne coûte
-- rien (critère 7).
CREATE TABLE ingestion_staging (
    -- ON DELETE CASCADE : l'aire de préparation n'a aucun sens sans son ingestion, et
    -- c'est ce qui garantit qu'une purge de dépôts ne laisse pas de lignes orphelines.
    ingestion_id text NOT NULL REFERENCES ingestions (id) ON DELETE CASCADE,
    -- Le rang de l'item dans le document. C'est la seule prise de l'appelant quand la clé
    -- n'a pas pu être extraite, et c'est aussi l'ordre d'écriture — « le dernier valide
    -- gagne » pour deux items de même clé suppose un ordre, et c'est celui-ci.
    position integer NOT NULL CHECK (position >= 0),
    -- Décidé à la PRÉPARATION : « a_ecrire » ou « rejete ». La transformation, la
    -- conformité au modèle et l'extraction de la clé ont lieu hors transaction, donc leur
    -- verdict est déjà connu quand la transaction s'ouvre.
    outcome text NOT NULL CHECK (outcome IN ('a_ecrire', 'rejete')),
    -- L'objet TRANSFORMÉ et son empreinte, tels qu'ils seront écrits. Nuls pour un item
    -- rejeté : il n'y a rien à écrire, et c'est `reason` qui porte l'information.
    cle text,
    objet jsonb,
    empreinte bytea,
    reason text,
    detail text,
    CHECK ((outcome = 'a_ecrire') = (objet IS NOT NULL AND empreinte IS NOT NULL AND cle IS NOT NULL)),
    PRIMARY KEY (ingestion_id, position)
);
