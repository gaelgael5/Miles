-- Ce qui a été CONFIÉ au module d'enrôlement, et quand (ticket edcf78bc).
--
-- POURQUOI GARDER UNE TRACE DE CE QU'ON A TRANSMIS. Le ticket demande une connexion saisie
-- une fois et « renouvelable d'un seul geste » : on remplace le PAT ici, et le module
-- d'enrôlement travaille avec le nouveau. La transmission est un appel réseau, donc elle
-- peut échouer — et un échec silencieux laisserait l'autre bout avec l'ancien credential
-- sans que personne le sache. Ces trois colonnes sont ce qui rend la divergence VISIBLE :
-- l'écran compare l'empreinte de ce qu'on détient à celle de ce qu'on a transmis, et dit
-- « à retransmettre » au lieu d'afficher « confiées » en y croyant.
--
-- POURQUOI UNE TABLE À ELLE, ET PAS DEUX COLONNES SUR `enrolment_peer`. `enrolment_peer` est
-- une table du socle : ses requêtes sont écrites une fois dans `miles_socle.pairing` et
-- servent les deux demandeurs. Y ajouter des colonnes propres au portail, c'est l'erreur
-- défaite le 29/10/2026 du côté du module d'environnement — l'upsert du pair ne peut pas
-- connaître les colonnes d'un seul produit. Rangée sous l'ORIGINE du pair, la trace devient
-- une jointure : réapparié ailleurs, on n'a rien transmis à celui-là, et c'est exactement
-- ce que l'écran doit dire.

-- La révision d'une transmission : strictement croissante, allouée au moment où l'on LIT
-- l'état à transmettre. Elle voyage dans la charge et le destinataire refuse une révision
-- inférieure à celle qu'il détient — sans quoi deux administrateurs qui changent deux
-- connexions en même temps peuvent laisser là-bas la plus vieille des deux photos.
--
-- Une séquence et non `max(revision) + 1` : la séquence ne recule pas, même si la ligne
-- d'état est supprimée par une révocation, et deux transmissions concurrentes n'obtiennent
-- jamais le même numéro.
CREATE SEQUENCE confided_git_revision;

CREATE TABLE confided_git_transmission (
    -- L'origine du module d'enrôlement À QUI l'on a transmis. La clé, et non `'self'` :
    -- ce qu'on a confié est confié à CELUI-LÀ, et un ré-appariement vers une autre origine
    -- ne doit pas hériter d'une trace qui ne le concerne pas.
    peer_base_url text PRIMARY KEY
        CHECK (peer_base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    revision bigint NOT NULL CHECK (revision >= 1),
    -- Empreinte de CE QUI a été transmis : identifiants, libellés, adresses, slugs des
    -- PAT et date de dernière modification de chacun, workspaces et dépôts. JAMAIS la
    -- valeur d'un credential, ni son empreinte : une empreinte de secret est un
    -- vérificateur pour une valeur devinée, et cette colonne est lisible par toute
    -- sauvegarde de la base. La date de modification du secret suffit à savoir qu'il a
    -- changé, et elle ne dit rien de sa valeur.
    content_digest text NOT NULL CHECK (content_digest ~ '^[0-9a-f]{64}$'),
    transmitted_at timestamptz NOT NULL
);
