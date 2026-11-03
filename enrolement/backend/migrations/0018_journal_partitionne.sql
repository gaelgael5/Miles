-- Partitionnement du journal d'events du module d'enrôlement à la journée, et purge par rétention.
-- Enabler 8e86afbc. La décision est du 18/10/2026 (rétention en nombre de jours
-- paramétrable), amendée le 26/10 (base par base) ; rien n'était partitionné jusqu'ici.
--
-- CE QUE CETTE MIGRATION CHANGE DANS LA FORME DU JOURNAL, et pourquoi elle y est obligée.
-- Mesuré le 03/11/2026 sur un PostgreSQL 16.15 jetable, pas déduit de la documentation :
--
--   1. « unique constraint on partitioned table must include all partitioning columns ».
--      `events(id)` ne peut donc plus être clé primaire seul : elle devient
--      `(id, written_at)`. Aucun index unique sur `id` seul n'est possible à côté — même
--      refus. L'identifiant reste unique DANS LES FAITS (un uuid4 par event), mais c'est
--      désormais l'application qui le garantit, non la base.
--
--   2. « cannot drop table events_20261106 because other objects depend on it / constraint
--      event_objects_…_fkey depends on table events_20261106 ». La clé étrangère de
--      `event_objects` EMPÊCHE la purge par suppression de partition, et aucun ordre
--      d'opérations ne les réconcilie. Elle est donc retirée — ce qui est cohérent sur le
--      fond : une rétention glissante EFFACE des events par construction, et une contrainte
--      qui l'interdit contredit la décision. À la place, `event_objects` porte `written_at`
--      recopié de l'event, est partitionné sur les MÊMES bornes, et les deux partitions du
--      même jour tombent dans la même transaction (`miles_socle.journal.maintenance`).
--      L'invariant « tout event_id désigne un event présent » est tenu par cette recopie et
--      par l'atomicité de la purge, et un test d'intégration l'éprouve.
--
-- `event_object_sequences` N'EST PAS touché : c'est de l'ÉTAT, pas du journal. Le purger
-- ferait repartir les numéros de séquence et casserait la monotonie dont tout le dispositif
-- dépend — y compris `ObjectHistory.missing_sequences`, qui signale une histoire incomplète
-- et qui est précisément ce qu'une purge produit.
--
-- Une partition par défaut serait un piège et non un filet : mesuré, elle attrape bien
-- l'insertion mais BLOQUE ensuite la création des partitions suivantes tant qu'elle n'est
-- pas vidangée. La réparation est à l'écriture (`miles_socle.events.journal`).

ALTER TABLE event_objects RENAME TO event_objects_avant_partition;
ALTER TABLE events RENAME TO events_avant_partition;

CREATE TABLE events (
    id uuid NOT NULL,
    type text NOT NULL,
    -- Date métier, distincte de la date d'écriture : une confirmation tardive, un
    -- import rejoué ou une reprise ont une date fonctionnelle qui n'est pas written_at.
    functional_at timestamptz NOT NULL,
    -- 'write_time' : l'appelant n'a pas fourni de date métier, on a pris written_at,
    -- et le lecteur doit le savoir.
    functional_at_source text NOT NULL CHECK (functional_at_source IN ('caller', 'write_time')),
    written_at timestamptz NOT NULL,
    -- L'identité utilisée (annuaire, sub), jamais la personne : une liaison
    -- d'identités tardive réunifie l'historique sans réécrire le journal.
    author_directory text NOT NULL CHECK (author_directory <> ''),
    author_subject text NOT NULL CHECK (author_subject <> ''),
    properties jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- `written_at` et non `functional_at` comme clé de partition : la date métier peut
    -- être ANTÉRIEURE (confirmation tardive) ou postérieure à l'écriture, et rangerait
    -- l'event dans une journée déjà purgée ou pas encore posée. La rétention porte sur
    -- l'âge du journal, c'est-à-dire sur la date d'écriture.
    PRIMARY KEY (id, written_at)
) PARTITION BY RANGE (written_at);

CREATE TABLE event_objects (
    object_kind text NOT NULL,
    object_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_id uuid NOT NULL,
    -- Recopié de l'event, jamais joint : c'est la clé de partition, et les deux tables
    -- doivent porter les mêmes bornes pour tomber ensemble.
    written_at timestamptz NOT NULL,
    -- `written_at` entre dans la clé primaire parce que PostgreSQL l'exige. L'unicité du
    -- triplet (kind, id, sequence) n'est donc plus garantie par la base : elle l'est par
    -- `event_object_sequences`, compteur monotone qui n'est jamais purgé.
    PRIMARY KEY (object_kind, object_id, sequence, written_at)
) PARTITION BY RANGE (written_at);

CREATE INDEX event_objects_event_id_idx ON event_objects (event_id, written_at);

DO $$
DECLARE
    jour date;
    events_avant bigint;
    objets_avant bigint;
    events_apres bigint;
    objets_apres bigint;
BEGIN
    SELECT count(*) INTO events_avant FROM events_avant_partition;
    SELECT count(*) INTO objets_avant FROM event_objects_avant_partition;

    -- Une partition par journée RÉELLEMENT présente dans l'ancien journal, plus
    -- aujourd'hui et sept jours d'avance. Les journées présentes d'abord : sans elles,
    -- la recopie échouerait sur « no partition of relation found for row ».
    FOR jour IN
        SELECT DISTINCT (written_at AT TIME ZONE 'UTC')::date FROM events_avant_partition
        UNION
        SELECT generate_series(current_date, current_date + 7, interval '1 day')::date
    LOOP
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF events FOR VALUES FROM (%L) TO (%L)',
            'events_' || to_char(jour, 'YYYYMMDD'),
            jour::timestamptz, (jour + 1)::timestamptz
        );
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF event_objects '
            'FOR VALUES FROM (%L) TO (%L)',
            'event_objects_' || to_char(jour, 'YYYYMMDD'),
            jour::timestamptz, (jour + 1)::timestamptz
        );
    END LOOP;

    INSERT INTO events (id, type, functional_at, functional_at_source, written_at,
                        author_directory, author_subject, properties)
    SELECT id, type, functional_at, functional_at_source, written_at,
           author_directory, author_subject, properties
    FROM events_avant_partition;

    INSERT INTO event_objects (object_kind, object_id, sequence, event_id, written_at)
    SELECT o.object_kind, o.object_id, o.sequence, o.event_id, e.written_at
    FROM event_objects_avant_partition o
    JOIN events_avant_partition e ON e.id = o.event_id;

    SELECT count(*) INTO events_apres FROM events;
    SELECT count(*) INTO objets_apres FROM event_objects;

    -- Le compte est COMPARÉ, pas supposé (critère 7 de l'enabler) : une recopie qui perd
    -- des lignes réussit sans rien dire, et la migration serait tamponnée « jouée ».
    IF events_apres <> events_avant OR objets_apres <> objets_avant THEN
        RAISE EXCEPTION
            'recopie du journal incomplete : events %/% , liens %/%',
            events_apres, events_avant, objets_apres, objets_avant;
    END IF;
END $$;

DROP TABLE event_objects_avant_partition;
DROP TABLE events_avant_partition;
