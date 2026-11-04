-- L'adresse où l'on JOINT le pair, distincte de son IDENTITÉ (ticket 1ce685e9).
--
-- POURQUOI DEUX COLONNES LÀ OÙ IL Y EN AVAIT UNE. `base_url` sert deux rôles qu'on
-- croyait indissociables tant qu'ils coïncidaient :
--   1. l'ORIGINE que le pair déclare, celle qui entre dans la chaîne signée de ses appels
--      vers nous, et la seule contre laquelle on vérifie l'origine déclarée d'un appel
--      entrant ;
--   2. l'ADRESSE que l'on compose pour l'appeler.
--
-- Le second rôle n'a aucun rapport avec la signature : la chaîne canonique porte l'origine
-- de l'ÉMETTEUR, la méthode, le chemin et l'empreinte du corps — jamais l'hôte appelé.
-- Composer ailleurs ne change donc rien à ce que le pair vérifie.
--
-- Mesuré le 29/10/2026 : le portail met un portillon d'authentification devant tout
-- service exposé, et un appel vers l'URL publique du module d'enrôlement reçoit 302 vers
-- sa page de connexion — le module ne voit JAMAIS la requête, son journal ne porte aucune
-- ligne. Le même appel signé, composé droit sur le module, est traité normalement.
ALTER TABLE enrolment_peer
    -- Même forme que l'identité : origine http(s) sans chemin. Un chemin la rendrait
    -- ambiguë, et deux écritures de la même adresse ne désigneraient plus la même cible.
    ADD COLUMN contact_url text
        CHECK (contact_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$');

-- Les lignes déjà en base prennent leur identité pour adresse de contact : c'est
-- exactement ce que le code faisait avant cette migration, donc c'est vrai pour elles, et
-- rien ne change de leur point de vue.
--
-- Remplies PUIS rendues obligatoires, plutôt que laissées nulles avec un repli dans le
-- code : un repli calculé à chaque appel serait indiscernable d'un bug le jour où la
-- valeur manquerait pour une autre raison. Ici l'absence n'est plus exprimable.
UPDATE enrolment_peer SET contact_url = base_url WHERE contact_url IS NULL;

ALTER TABLE enrolment_peer
    ALTER COLUMN contact_url SET NOT NULL;
