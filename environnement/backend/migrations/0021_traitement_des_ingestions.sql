-- Les états du TRAITEMENT d'une ingestion, et son compte-rendu (story d680e811).
--
-- La migration 0018 n'admettait qu'un seul état — « recu » — et son commentaire annonçait
-- celle-ci : « Les états du traitement viendront avec le ticket qui traite, et avec leur
-- propre migration. » C'est elle.
--
-- LA CONTRAINTE EST CHERCHÉE, PAS NOMMÉE. Elle est auto-nommée par PostgreSQL, qui ajoute
-- un suffixe en silence quand le nom est déjà pris — `ingestions_state_check1`. Écrire le
-- nom présumé ferait échouer la migration sur une base où ce suffixe existe, et c'est le
-- genre d'écart qui ne se découvre que sur une base ancienne. On la retrouve donc par la
-- colonne qu'elle porte, ce qui est vrai de toutes les bases.
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

ALTER TABLE ingestions ADD CONSTRAINT ingestions_etat
    CHECK (state IN ('recu', 'traite', 'rejete'));

-- NULL tant que le lot n'est pas traité, et c'est la distinction qui porte la reprise
-- (critère 14) : un service arrêté au milieu du traitement laisse la transaction annulée,
-- donc l'état « recu » et aucun compte-rendu. Le même dépôt rejoué REPREND le traitement
-- au lieu de rendre un compte-rendu vide — rien n'avait été écrit, il n'y a donc ni
-- doublon ni perte. Un défaut à '{}' aurait rendu ces deux situations indiscernables.
--
-- POURQUOI LE COMPTE-RENDU EST EN BASE, et pas seulement rendu à l'appelant : il est la
-- réponse synchrone d'un dépôt `element` ou `tableau`, et une réponse HTTP se perd. Un
-- partenaire qui rejoue son dépôt avec la MÊME clé d'idempotence doit obtenir le même
-- compte-rendu que la première fois (critère 13), et non un compte-rendu vide qui lui
-- ferait croire que son lot n'a rien écrit. C'est aussi ce qui rend lisible, des semaines
-- plus tard, pourquoi tel objet d'un import n'est jamais arrivé.
ALTER TABLE ingestions ADD COLUMN report jsonb;

-- « rejete » : TOUS les objets du lot ont été rejetés (critère 12). L'ingestion reste en
-- base — elle est arrivée, et c'est la règle « le lot est persisté avant toute
-- transformation » — mais aucune ligne de storage n'a bougé, `vu_le` compris.
