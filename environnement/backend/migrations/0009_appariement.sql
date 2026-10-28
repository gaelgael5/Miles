-- La demande d'appariement en cours, côté environnement (ticket 6a0daab6).
--
-- POURQUOI UNE TABLE, et non un état gardé en mémoire : l'appariement se fait en deux
-- gestes séparés par un aller-retour humain — frapper chez le module d'enrôlement, puis
-- coller le code qu'un administrateur y lit. Entre les deux, le processus peut redémarrer,
-- et l'écran peut être rouvert depuis une autre instance. Un état en mémoire ferait
-- échouer l'appariement par intermittence, et le diagnostic partirait sur le code.
CREATE TABLE pairing_attempt (
    -- Une SEULE tentative à la fois, garantie par le modèle : un environnement n'est
    -- apparié qu'à un module d'enrôlement, donc deux demandes en cours n'auraient aucun
    -- sens — et la seconde ferait oublier vers qui la première avait frappé.
    id text PRIMARY KEY CHECK (id = 'self'),
    -- L'origine du module d'enrôlement chez qui on a frappé. C'est elle qu'il faudra
    -- rappeler pour confirmer : sans elle, le code collé n'aurait pas de destinataire.
    base_url text NOT NULL CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    created_at timestamptz NOT NULL
);
