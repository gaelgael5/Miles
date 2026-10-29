-- La révocation d'un appariement (ticket d5ffeb33).
--
-- IL N'Y A PAS DE COLONNE « RÉVOQUÉ » SUR `environment_peer`, ET C'EST LE CŒUR DU TICKET.
-- Révoquer SUPPRIME la ligne, donc la clé publique du pair avec elle : le critère 8
-- demande des clés détruites, « pas seulement marquées inactives ». Un drapeau laisserait
-- la clé en base, à portée du premier code qui oublierait de le lire — et l'oubli d'un
-- filtre ne se voit jamais en test, seulement en production.
--
-- POURQUOI UNE PIERRE TOMBALE, ALORS QUE LE PROTOCOLE EN REFUSE UNE POUR LES DEMANDES.
-- `PairingStatusOut` explique pourquoi ce module ne garde AUCUNE trace d'une demande
-- disparue : une trace par tentative serait un état de plus à purger, et dirait à qui
-- frappe au hasard si une origine a déjà été refusée. Celle-ci diffère sur les deux
-- points. Elle est par appariement CONCLU — bornée par le nombre d'environnements
-- réellement appariés, pas par le nombre de tentatives — et surtout elle ne change
-- AUCUNE réponse servie : un appel signé d'une origine révoquée reçoit le même 401
-- opaque, mot pour mot. Elle ne change que la ligne de JOURNAL, qui dira « origine
-- révoquée » au lieu de « origine inconnue ». C'est le critère 4, et sans lui le
-- diagnostic part chercher une clé perdue alors qu'un humain a décidé.
CREATE TABLE revoked_pairing (
    -- Même clé que l'appariement qu'elle remplace, et même forme : c'est l'origine
    -- déclarée d'un appel signé qu'on vient confronter ici, après n'avoir trouvé aucun
    -- pair.
    base_url text PRIMARY KEY
        CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    -- L'EMPREINTE de la clé révoquée, jamais la clé. Une empreinte ne vérifie aucune
    -- signature : la garder ne laisse pas l'appariement utilisable d'un demi-pas. Elle
    -- sert au diagnostic d'un ré-appariement, dont la première question est toujours
    -- « la stack est-elle revenue avec la même clé, ou en a-t-elle changé ? ».
    public_key_fingerprint text NOT NULL,
    revoked_at timestamptz NOT NULL
);

-- L'environnement quitté n'est PAS recopié ici, et c'est délibéré. Il est dans l'event
-- `pairing.revoked`, avec son identifiant, son slug et son libellé figés au moment du
-- geste — le journal est fait pour ça. Le recopier donnerait deux sources pour la même
-- information, dont une seule serait tenue à jour, et la pierre tombale deviendrait un
-- second référentiel que personne n'a demandé.
--
-- Conséquence voulue : révoquer ne verrouille RIEN dans le référentiel. L'environnement
-- quitté redevient libre immédiatement — `environment_peer` ne le référence plus — et
-- peut être réapparié ou supprimé par le geste du référentiel (critère 12).
