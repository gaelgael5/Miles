-- L'environnement assigné sort de la ligne du pair et prend sa propre table, rangé sous
-- l'ORIGINE du pair qui l'a dit (ticket ba44914b).
--
-- POURQUOI DÉFAIRE CE QUE LA MIGRATION 13 VENAIT DE POSER, UN JOUR PLUS TARD. La 13 disait
-- « sur la ligne du pair, et pas dans une table à part : ce rattachement n'existe que par
-- l'appariement, et une table séparée permettrait d'en garder un alors qu'aucun pair ne le
-- revendique ». La crainte était juste, la solution était la mauvaise : ce n'était pas la
-- table qui portait l'invariant, c'était trois clauses `CASE` dans l'upsert du pair, qui
-- effaçaient la mémoire quand l'identité du pair changeait.
--
-- Or cet upsert est passé AU SOCLE le 29/10/2026 : le module de paramétrage s'apparie au
-- même module d'enrôlement, par le même mécanisme, et le ticket interdit d'en dupliquer un
-- second. Une requête du socle ne peut pas porter le nom de colonnes qui n'existent que
-- dans un produit sur deux — et la contourner par un crochet aurait fait d'un invariant du
-- modèle une clause à ne pas oublier d'appeler.
--
-- Rangée sous l'origine du pair, la mémoire cesse de s'appliquer D'ELLE-MÊME dès que cette
-- origine change : la lecture joint sur le pair courant et ne la trouve plus. L'invariant
-- est devenu une jointure au lieu d'être une clause, et la crainte de la 13 est levée — une
-- ligne qu'aucun pair ne revendique n'est jamais lue.
--
-- Conséquence voulue, et elle est meilleure que l'ancienne : une stack qui revient chez un
-- enrôlement qu'elle avait quitté retrouve ce que CELUI-LÀ lui avait dit, non frais et daté
-- de l'époque. C'est vrai, et la date le dit. L'effacement de la version 13 prétendait, lui,
-- qu'on n'avait jamais rien su.
CREATE TABLE assigned_environment (
    -- L'origine du module d'enrôlement qui a dit cette valeur. CLÉ de la table, et non une
    -- colonne de plus : c'est ce qui fait qu'une valeur ne peut pas être attribuée à un
    -- pair qui ne l'a pas dite. Même forme que partout ailleurs — origine http(s) sans
    -- chemin, celle qui entre dans la chaîne signée.
    base_url text PRIMARY KEY CHECK (base_url ~ '^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?$'),
    -- Le slug et le libellé, jamais l'identifiant : celui-ci est la clé du référentiel de
    -- l'enrôlement, et le ranger ici écrirait une relation entre deux bases que personne
    -- ne réconcilie. Les deux sont NOT NULL ensemble, ce que la 13 devait exprimer par un
    -- CHECK sur trois colonnes nullables — « rattaché » est une seule information, et un
    -- slug sans libellé ne s'afficherait pas.
    slug text NOT NULL,
    label text NOT NULL,
    -- La date à laquelle NOUS avons reçu cette valeur, avec NOTRE horloge. Obligatoire ici
    -- alors qu'elle était nullable : « jamais lu » ne se dit plus par des colonnes vides,
    -- il se dit par l'ABSENCE de ligne. Un repli qui ne dit pas qu'il en est un est
    -- indiscernable d'un bug, et une date facultative rendait ce silence possible.
    fetched_at timestamptz NOT NULL
);

-- Aucune clé étrangère vers `enrolment_peer`, et c'est délibéré : sa clé primaire est
-- `id = 'self'`, pas `base_url`. Référencer la seconde demanderait de l'unicifier, donc de
-- promettre qu'une origine n'y figure qu'une fois — ce que la table garantit déjà
-- autrement, puisqu'elle n'a qu'une ligne. La jointure de lecture suffit, et elle ne peut
-- pas être oubliée : il n'existe aucune requête qui lise cette table sans elle.

-- Ce que la 13 avait pu mémoriser est REPRIS, pas jeté : la valeur est vraie, elle porte sa
-- date, et l'administrateur la voit à l'écran depuis le déploiement de la veille. La perdre
-- afficherait « aucun environnement n'a jamais été lu » d'une stack qui en connaît un.
INSERT INTO assigned_environment (base_url, slug, label, fetched_at)
SELECT base_url, environment_slug, environment_label, environment_fetched_at
FROM enrolment_peer
WHERE environment_slug IS NOT NULL;

-- Puis les colonnes disparaissent. Les laisser ferait deux sources pour une même valeur,
-- dont une seule serait tenue à jour — et c'est toujours celle que personne ne lit qui
-- finit par être lue.
ALTER TABLE enrolment_peer
    DROP CONSTRAINT enrolment_peer_environment_complet,
    DROP COLUMN environment_slug,
    DROP COLUMN environment_label,
    DROP COLUMN environment_fetched_at;
