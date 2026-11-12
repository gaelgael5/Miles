-- Un CURSEUR sur le journal : un entier qui ne recule jamais, pour qu'un consommateur
-- puisse dire « j'ai traité jusque-là » et reprendre sans relire ni sauter.
-- Demandé par Gael le 12/11/2026, en vue des automates qui dépileront les events dans
-- cet ordre pour les scénarios.
--
-- CE QUE LA MESURE A IMPOSÉ (PostgreSQL 16.15 jetable, 12/11/2026 — pas déduit de la
-- documentation). La table est PARTITIONNÉE, et cela écarte la forme évidente :
--
--   1. `ALTER TABLE events ADD COLUMN ... GENERATED AS IDENTITY` est REFUSÉ :
--      « cannot recursively add identity column to table that has child tables ».
--      Une colonne d'identité ne s'ajoute pas à une table qui a déjà des partitions.
--      D'où la séquence explicite ci-dessous, qui fait exactement le même travail.
--   2. Un index UNIQUE sur `cursor_seq` seule est REFUSÉ, comme pour `id` :
--      « unique constraint on partitioned table must include all partitioning columns ».
--      L'unicité est donc tenue par la SÉQUENCE, pas par la base — même situation que
--      `id`, et pour la même raison. L'index posé est simple, et c'est lui qui sert la
--      lecture par curseur.
--   3. Le défaut est propagé à chaque partition, et toutes pointent la MÊME séquence :
--      l'ordre est donc global au journal, et non par jour. Une partition créée après
--      coup hérite du défaut — le créateur de partitions n'a rien à changer.
--   4. Retirer une partition ne fait pas reculer la séquence : la purge de rétention
--      laisse un trou dans les valeurs, jamais un recul.
--
-- CE QUE CE CURSEUR NE GARANTIT PAS, et qui décide de la forme des automates : un numéro
-- est pris à l'INSERT, pas au COMMIT. Mesuré le 12/11/2026 : une transaction lente peut
-- détenir 6 pendant que 4 est déjà visible. Un consommateur qui lirait « tout ce qui est
-- supérieur à mon dernier vu » sauterait donc définitivement l'event de la transaction
-- lente. C'est au consommateur de s'en garder — pas à cette colonne.
CREATE SEQUENCE events_cursor_seq AS bigint;

-- Nullable d'abord, parce que le remplissage doit être DÉTERMINISTE : avec un défaut posé
-- dès l'ajout, les lignes existantes prennent leur numéro dans l'ordre physique du tas,
-- partition par partition. Ici l'ordre est celui de l'écriture, puis de l'identifiant pour
-- départager deux events de la même microseconde — le même ordre que celui de l'écran.
ALTER TABLE events ADD COLUMN cursor_seq bigint;

WITH ordonnes AS (
    SELECT id, written_at, row_number() OVER (ORDER BY written_at, id) AS rang FROM events
)
UPDATE events e SET cursor_seq = o.rang
FROM ordonnes o WHERE e.id = o.id AND e.written_at = o.written_at;

-- `false` en troisième argument : la séquence n'a pas encore été appelée, donc le prochain
-- `nextval` rend exactement cette valeur. Sans lui, le premier event après la migration
-- sauterait un numéro.
SELECT setval('events_cursor_seq', coalesce((SELECT max(cursor_seq) FROM events), 0) + 1, false);

ALTER TABLE events ALTER COLUMN cursor_seq SET NOT NULL;
ALTER TABLE events ALTER COLUMN cursor_seq SET DEFAULT nextval('events_cursor_seq');

-- Simple et non unique (voir le point 2 ci-dessus). C'est l'index de la lecture par
-- curseur : `WHERE cursor_seq > $1 ORDER BY cursor_seq LIMIT n`. Mesuré : le plan est un
-- parcours d'index par partition, fusionné — une lecture par curseur touche donc TOUTES
-- les partitions, et un consommateur qui connaît la date de son dernier event traité a
-- intérêt à borner aussi `written_at` pour que l'élagage joue.
CREATE INDEX events_cursor_seq_idx ON events (cursor_seq);

COMMENT ON COLUMN events.cursor_seq IS
    'Curseur du journal : entier croissant, global à la base, jamais réutilisé. '
    'Attribué à l''INSERT et non au COMMIT : un consommateur doit se garder du trou. '
    'Les events antérieurs au 12/11/2026 sont numérotés par (written_at, id).';
