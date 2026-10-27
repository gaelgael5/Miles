-- Journal d'events du module d'enrôlement : toute modification écrit son event dans SA
-- transaction, et dans SA base. Le journal ne quitte jamais le produit qui l'écrit
-- (cadrage, « Un dépôt, trois images ») : un journal partagé ramènerait les écritures
-- des trois produits vers une base unique et ferait tomber la règle de la transaction
-- unique. Les journaux ne se recollent donc pas d'un produit à l'autre, et c'est la clé
-- de corrélation qui recoud une histoire.
CREATE TABLE events (
    id uuid PRIMARY KEY,
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
    properties jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Un numéro de séquence par objet, et non un chaînage par référence : chaîner
-- obligerait à relire le dernier event avant chaque écriture. Le compteur est une
-- ligne par objet : seul l'objet est verrouillé, jamais la table.
CREATE TABLE event_object_sequences (
    object_kind text NOT NULL,
    object_id text NOT NULL,
    last_sequence bigint NOT NULL CHECK (last_sequence > 0),
    PRIMARY KEY (object_kind, object_id)
);

CREATE TABLE event_objects (
    object_kind text NOT NULL,
    object_id text NOT NULL,
    sequence bigint NOT NULL CHECK (sequence > 0),
    event_id uuid NOT NULL REFERENCES events (id),
    PRIMARY KEY (object_kind, object_id, sequence)
);

CREATE INDEX event_objects_event_id_idx ON event_objects (event_id);
