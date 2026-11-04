-- Index de consultation du journal d'events (story 50bfcba0).
-- Jusqu'ici `events` ne portait AUCUN index hors sa clé primaire : même le minimum
-- demandé par Gael — « au minimum la date de l'event le type » — en exigeait un.
--
-- POSÉS SUR LA TABLE PARTITIONNÉE, et c'est mesuré le 03/11/2026 sur un PostgreSQL 16.15 :
-- un index déclaré sur le parent est repris AUTOMATIQUEMENT par les partitions créées
-- ensuite. La partition que l'entretien posera demain portera donc ces index sans que
-- personne y pense, et retirer une partition emporte les siens sans toucher au parent.
-- C'est ce qui rend ces index compatibles avec une rétention glissante.
--
-- `written_at DESC` : l'écran montre le plus récent d'abord, et un index ascendant obligerait
-- PostgreSQL à le parcourir à l'envers — ce qu'il sait faire, mais sans pouvoir s'arrêter
-- tôt sur un `LIMIT` combiné à un autre critère.

-- « Qu'est-ce qui s'est passé cette semaine » : la recherche sans autre filtre, qui est le
-- défaut de la route. La clé de partition borne déjà les partitions lues ; cet index donne
-- l'ordre à l'intérieur de chacune.
CREATE INDEX events_written_at_idx ON events (written_at DESC);

-- « Tous les events de ce type, les plus récents d'abord ». Le type en tête : c'est
-- l'égalité, et la date ne sert qu'à ordonner ce qu'elle a sélectionné.
CREATE INDEX events_type_written_at_idx ON events (type, written_at DESC);

-- « Qu'a fait ce compte », et donc aussi « qu'a fait cette clé d'API » : une écriture
-- déléguée porte `apikey` comme annuaire et l'identifiant de la clé comme sujet.
CREATE INDEX events_author_written_at_idx
    ON events (author_directory, author_subject, written_at DESC);

-- La date FONCTIONNELLE, distincte de la date d'écriture : une confirmation tardive ou un
-- import rejoué portent une date métier antérieure. Deux filtres, donc deux index — les
-- confondre rendrait l'un des deux inutilisable.
CREATE INDEX events_functional_at_idx ON events (functional_at DESC);

-- « L'historique de cet objet » ne demande RIEN : `event_objects` porte déjà
-- (object_kind, object_id, sequence, written_at) en clé primaire, et c'est son préfixe
-- qui sert ce filtre.
