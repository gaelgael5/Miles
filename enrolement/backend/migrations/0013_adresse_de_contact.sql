-- L'adresse où JOINDRE un environnement apparié, distincte de son identité (ticket 4ce141d3).
--
-- MIROIR EXACT de la migration 11 du module d'environnement, et pour la même raison : la
-- chaîne canonique signée porte l'origine de l'ÉMETTEUR, la méthode, le chemin et
-- l'empreinte du corps — jamais l'hôte appelé. Composer ailleurs ne change donc rien à ce
-- que le pair vérifie.
--
-- POURQUOI CE MODULE EN A BESOIN MAINTENANT. Jusqu'au 29/10/2026 il n'émettait aucun
-- appel : les environnements l'appelaient, il répondait. La révocation renverse ce sens —
-- il doit PRÉVENIR la stack qu'il lui retire l'accès, sans quoi l'écran d'en face ne peut
-- qu'énumérer les causes possibles de son refus. Et l'URL publique d'un environnement
-- passe par le portillon du portail : l'avis n'y arriverait pas.
ALTER TABLE environment_peer
    -- Même forme que l'identité : origine http(s) sans chemin.
    ADD COLUMN contact_url text
        CHECK (contact_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$');

-- Les lignes déjà en base prennent leur identité pour adresse de contact : c'est ce que
-- ferait un module qui n'aurait jamais connu cette distinction, donc c'est vrai pour
-- elles. Remplies PUIS rendues obligatoires, plutôt que laissées nulles avec un repli
-- dans le code : un repli calculé à chaque appel serait indiscernable d'un bug le jour où
-- la valeur manquerait pour une autre raison.
UPDATE environment_peer SET contact_url = base_url WHERE contact_url IS NULL;

ALTER TABLE environment_peer
    ALTER COLUMN contact_url SET NOT NULL;

-- ELLE EST SAISIE PAR L'ADMINISTRATEUR DE CE MODULE, jamais déclarée par la stack qui
-- frappe (arbitrage de Gael du 29/10/2026). Laisser un tiers que personne n'a encore
-- authentifié désigner l'adresse vers laquelle ce module émettra des appels signés
-- reviendrait à lui confier le choix de la cible. Celui qui compose reste maître de ce
-- qu'il compose.
