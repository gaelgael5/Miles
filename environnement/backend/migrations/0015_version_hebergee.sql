-- La version du workspace que cette stack SERT (story 3bbd4f87, demande de Gael du
-- 01/11/2026 : « il faut une api pour demander à l'environement de faire un pull dans la
-- version demandé et que le system se mette à jour »).
--
-- CE QUE CETTE TABLE N'EST PAS : la source de vérité du paramétrage. Celle-ci est dans
-- git, invariant du projet — ici ne vivent que l'ORDRE reçu et la trace de ce qu'on en a
-- fait. Le contenu, lui, est posé sur le volume, et c'est `git rev-parse HEAD` qui dit ce
-- qui est réellement servi. Croire cette table plutôt que l'arbre ferait répondre
-- « à jour » à un module qui a perdu son disque.
CREATE TABLE hosted_version (
    -- Une SEULE ligne, garantie par le modèle et non par le code — même idiome que
    -- `module_identity` : cette stack sert UN workspace, celui que l'enrôlement lui a
    -- placé. Deux lignes voudraient dire deux paramétrages pour un environnement, et plus
    -- aucune réponse unique à « que sert cette stack ? ».
    id text PRIMARY KEY CHECK (id = 'self'),
    -- Le workspace tel que l'enrôlement le nomme. Sa forme est la sienne, pas la nôtre :
    -- on vérifie ce qui empêche une charge démesurée d'être écrite, et rien de plus.
    workspace_id text NOT NULL
        CHECK (char_length(workspace_id) BETWEEN 1 AND 200 AND workspace_id !~ '[[:cntrl:]]'),
    ordered_number integer NOT NULL CHECK (ordered_number >= 1),
    -- Le commit complet. C'est lui qui PIN le contenu : il arrive dans un ordre signé par
    -- l'enrôlement, et le bundle qui revient du relais — dont la réponse, elle, n'est pas
    -- signée — est refusé s'il ne le porte pas exactement.
    ordered_commit text NOT NULL CHECK (ordered_commit ~ '^[0-9a-f]{40}$'),
    -- NOTRE horloge, pas celle de l'enrôlement : deux horloges dérivent, et la dérive a
    -- son propre refus à l'appariement. Ce qu'on date ici, c'est la réception.
    ordered_at timestamptz NOT NULL,
    served_commit text CHECK (served_commit IS NULL OR served_commit ~ '^[0-9a-f]{40}$'),
    served_at timestamptz,
    -- Le code du refus quand l'application n'a pas abouti. Court, sans caractère de
    -- contrôle : il repart vers l'enrôlement, qui l'affiche à son administrateur.
    refusal text CHECK (refusal IS NULL
        OR (char_length(refusal) BETWEEN 1 AND 40 AND refusal ~ '^[a-z][a-z0-9_]*$')),
    -- Servi OU refusé, jamais les deux, et la date va avec la valeur : un commit servi
    -- sans date le ferait passer pour frais, et une date sans commit pour un vide daté.
    CONSTRAINT hosted_version_etat_coherent CHECK (
        (served_commit IS NULL) = (served_at IS NULL)
        AND NOT (served_commit IS NOT NULL AND refusal IS NOT NULL)
    )
);

COMMENT ON TABLE hosted_version IS
    'L''ordre reçu de l''enrôlement et ce que cette stack en a fait. Le paramétrage '
    'lui-même est dans git, sur le volume : cette table ne porte que le choix et sa trace.';
