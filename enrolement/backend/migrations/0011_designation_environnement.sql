-- La désignation de l'environnement d'une demande d'appariement (ticket bf2115cd).
--
-- POURQUOI LA DÉSIGNATION VIT SUR LA DEMANDE, ET PAS SEULEMENT SUR L'APPARIEMENT.
-- Révéler le code EST le geste d'acceptation (ticket ce66f5bb) : la désignation doit donc
-- précéder la révélation, donc exister avant que l'appariement ne soit conclu. La porter
-- uniquement sur `environment_peer` obligerait à rattacher APRÈS coup — et personne ne
-- rattrape un état qui marche : le device n'arriverait pas, on ne saurait pas pourquoi,
-- et l'écran dirait « apparié ».
ALTER TABLE pairing_request
    -- RESTRICT comme sur l'appariement : supprimer un environnement que l'humain vient de
    -- désigner ne doit pas effacer la désignation en silence. Le référentiel refuse la
    -- suppression en la nommant ; un SET NULL laisserait l'écran dire « code non
    -- révélable » sans que rien n'explique pourquoi.
    ADD COLUMN environment_id uuid REFERENCES environment (id) ON DELETE RESTRICT;

-- Pas d'UNIQUE ici, à la différence de `environment_peer`. Deux demandes peuvent viser le
-- même environnement : tant qu'aucune n'est conclue, aucune ne le CONSOMME — une demande
-- refusée ou expirée doit le laisser libre. C'est la conclusion qui tranche, et l'unicité
-- qui la tient est celle de `environment_peer.environment_id` : la seconde confirmation
-- est refusée en le disant, plutôt que d'écraser la première.
