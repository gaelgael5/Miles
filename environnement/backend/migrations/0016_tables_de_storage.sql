-- La trace de ce qui a été posé en base pour chaque storage de la version servie
-- (demande de Gael du 02/11/2026 : « dans environnement assure toi que les tables de
-- stockages fonctionnelles soient créées »).
--
-- CE QUE CETTE TABLE N'EST PAS : la source de vérité de la forme des tables. Celle-ci est
-- le CATALOGUE de PostgreSQL, qu'on interroge pour savoir ce qui existe vraiment — un
-- volume restauré, une base recréée, une colonne retirée à la main laisseraient cette
-- table affirmer une forme qui n'est plus là. Ce qu'elle porte, c'est ce qu'on a FAIT, et
-- le SQL qu'on a appliqué : sans homologation préalable, c'est la seule façon de relire
-- après coup ce qui s'est exécuté sur la base de cet environnement.
CREATE TABLE storage_schema (
    -- Le nom du storage, tel que la déclaration le porte. La même règle de nommage que
    -- celle qui autorise à en faire une table : si elle ne passe pas, rien n'est posé et
    -- le refus est enregistré par cette même ligne.
    storage text PRIMARY KEY
        CHECK (char_length(storage) BETWEEN 2 AND 63 AND storage ~ '^[a-z0-9][a-z0-9-]*$'),
    -- Le schéma et la table réellement visés. Nuls quand la déclaration a été refusée
    -- avant d'avoir pu les déterminer — un domaine invalide, par exemple.
    schema_name text
        CHECK (schema_name IS NULL OR schema_name ~ '^[a-z0-9][a-z0-9_-]*$'),
    table_name text
        CHECK (table_name IS NULL OR table_name ~ '^[a-z0-9][a-z0-9_-]*$'),
    -- Le modèle stocké, « domaine/nom », pour relire la déclaration sans ouvrir git.
    model text CHECK (model IS NULL OR char_length(model) BETWEEN 3 AND 130),
    -- La version de paramétrage qui a produit cet état. C'est elle qui rend un résultat
    -- contesté reproductible : la forme de la table est une conséquence du paramétrage,
    -- et sans la version on ne sait pas de quel paramétrage.
    version_number integer CHECK (version_number IS NULL OR version_number >= 1),
    -- Le SQL appliqué, dans l'ordre. Lisible après coup, puisque personne ne l'a relu
    -- avant : c'est la contrepartie exigée au ticket, et elle ne remplace pas une
    -- homologation — elle permet seulement de constater.
    statements jsonb NOT NULL DEFAULT '[]'::jsonb,
    applied_at timestamptz,
    -- Le motif de refus, quand ce storage n'a pas été matérialisé. Nommé, jamais tu :
    -- un storage absent de la base sans refus enregistré serait un angle mort.
    refusal text CHECK (refusal IS NULL
        OR (char_length(refusal) BETWEEN 1 AND 40 AND refusal ~ '^[a-z][a-z0-9_]*$')),
    -- Ce que le refus désigne : un chemin, un nom de colonne, le modèle manquant. Vient
    -- du paramétrage, donc sa longueur se borne et ses caractères de contrôle se
    -- refusent — il repart vers un écran.
    refusal_detail text CHECK (refusal_detail IS NULL
        OR (char_length(refusal_detail) BETWEEN 1 AND 300 AND refusal_detail !~ '[[:cntrl:]]')),
    -- Posé OU refusé, jamais les deux. Un storage dont la table est là ET qui porte un
    -- refus ne dirait pas lequel des deux croire.
    CONSTRAINT storage_schema_etat_coherent CHECK (
        (applied_at IS NULL) = (refusal IS NOT NULL)
        AND (refusal IS NOT NULL OR (schema_name IS NOT NULL AND table_name IS NOT NULL))
        AND (refusal IS NOT NULL OR version_number IS NOT NULL)
        AND (refusal IS NOT NULL OR jsonb_typeof(statements) = 'array')
        AND (refusal IS NOT NULL OR refusal_detail IS NULL)
    )
);

COMMENT ON TABLE storage_schema IS
    'Ce qui a été posé en base pour chaque storage de la version servie, et le SQL '
    'appliqué. La forme réelle des tables se lit dans le catalogue de PostgreSQL, pas ici.';
