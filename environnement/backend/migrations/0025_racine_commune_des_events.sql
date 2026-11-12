-- Les trois champs de la racine technique commune des events (Gael, 12/11/2026) :
-- « ils tombent tous dans la meme table avec une racine technique d'event qui est la meme
-- et qui est basée sur le package urban-workflow ». Le journal portait déjà quatre des
-- sept champs sous d'autres noms (type, id, functional_at, written_at) ; voici les trois
-- qui manquaient. La correspondance complète est dans `miles_socle.events.root`.
--
-- NULLABLES, et c'est voulu : un geste humain dans l'atelier n'a ni identifiant chez un
-- producteur, ni clé d'anti-doublon, ni date de création ailleurs. Les events déjà écrits
-- les ont donc nuls, et la relecture doit le supporter — un test l'éprouve.
--
-- `ExternalId` n'est PAS unique : deux réceptions du même message doivent rester visibles
-- dans le journal, c'est ce qui rend l'idempotence constatable après coup (décision de
-- l'epic « Journal d'events »). Une contrainte d'unicité ici effacerait la preuve.
--
-- Aucun index : rien ne filtre encore sur ces colonnes, et un index sur un journal
-- partitionné coûte à chaque écriture. Il viendra avec l'écran qui en a besoin.
ALTER TABLE events
    ADD COLUMN external_id text,
    ADD COLUMN dedup_key text,
    ADD COLUMN creation_date timestamptz;

-- Garde de dernier recours, en plus du refus applicatif : une chaîne vide dirait que le
-- producteur croyait poser une valeur. Elle passe quand la colonne est nulle.
ALTER TABLE events
    ADD CONSTRAINT events_external_id_non_vide CHECK (external_id <> ''),
    ADD CONSTRAINT events_dedup_key_non_vide CHECK (dedup_key <> '');
