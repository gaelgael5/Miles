-- L'avis de révocation reçu du module d'enrôlement (ticket 4ce141d3).
--
-- POURQUOI ON LE RETIENT PLUTÔT QUE DE LE DÉDUIRE. Sans lui, cet écran ne pouvait
-- qu'énumérer : « son administrateur a pu révoquer, OU les clés ne se correspondent
-- plus ». Un message qui énumère n'aide personne à agir, et c'est le constat qui a motivé
-- ce ticket. L'enrôlement ne pouvait pas nous le dire en RÉPONSE — révoquer détruit notre
-- clé publique chez lui, donc il ne peut plus vérifier que c'est bien nous qui demandons,
-- et répondre « tu es révoqué » à qui déclare notre origine l'apprendrait à n'importe qui.
-- Il nous le POUSSE donc, signé de SA clé, que nous détenons encore.
ALTER TABLE enrolment_peer
    -- Nul = aucun avis reçu, et c'est l'état normal. Non nul = la date à laquelle NOUS
    -- avons reçu l'avis, pas celle que l'enrôlement aurait annoncée : les horloges des
    -- deux modules dérivent — l'appariement a son propre refus pour ça — et dater avec la
    -- nôtre vaut mieux que de croire la sienne pour un affichage.
    ADD COLUMN revoked_at timestamptz;

-- La LIGNE RESTE. On ne détruit rien en apprenant qu'on est révoqué : l'empreinte de
-- l'ancien appariement est ce que l'administrateur voudra comparer après avoir refrappé,
-- et un écran qui se vide ne dit pas ce qui s'est passé — il dit seulement qu'il n'y a
-- rien, ce qui est le message d'un module qui n'a jamais été apparié.
--
-- Le ré-appariement efface cette date : `db_upsert_peer` l'écrase à chaque écriture, et
-- une stack réappariée n'est plus révoquée. La garder ferait dire « révoqué » d'un
-- appariement vivant, soit exactement le contresens que ce ticket corrige.
