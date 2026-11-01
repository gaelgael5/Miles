-- La version du workspace qu'un environnement doit servir (demande de Gael du 01/11/2026,
-- story 3bbd4f87) : « on peu demander à associer une version de la configuration ».
--
-- TABLE À ELLE ET NON SIX COLONNES SUR `environment`. Trois raisons, et la première
-- suffit : l'ABSENCE de ligne dit « aucune version ordonnée », là où six colonnes nulles
-- demanderaient à chaque lecture de décider lesquelles vont ensemble. Ensuite, ce qui est
-- ici a son propre cycle — on ordonne, le pair répond — et n'a pas la même durée de vie
-- que le référentiel. Enfin, `environment` est le référentiel : y verser l'état de chaque
-- dispositif en ferait un fourre-tout que plus personne ne relit.
CREATE TABLE hosted_version (
    -- Clé PRIMAIRE et non simple référence : un environnement ne sert qu'UNE version à la
    -- fois. L'historique des choix est au journal d'events, qui est fait pour ça ; une
    -- deuxième ligne ici ne dirait pas laquelle est servie.
    environment_id uuid PRIMARY KEY REFERENCES environment(id) ON DELETE CASCADE,
    -- Le numéro tel que l'étiquette `version/<n>` le porte. Il sert à l'écran et au
    -- journal ; ce qui identifie le contenu, c'est le commit.
    number integer NOT NULL CHECK (number >= 1),
    -- Le commit complet, et la forme est contrainte ICI parce que cette valeur voyage
    -- jusque dans une commande git chez le pair. Un préfixe court ne se récupère pas d'une
    -- forge, et deux commits pourraient le partager.
    commit_sha text NOT NULL CHECK (commit_sha ~ '^[0-9a-f]{40}$'),
    ordered_at timestamptz NOT NULL,
    -- CE QUE LE PAIR A RÉPONDU la dernière fois qu'on lui a poussé l'ordre, et rien de
    -- plus : c'est un instantané daté, pas une vérité courante. Nul tant qu'il n'a pas
    -- répondu — distinct d'une réponse disant qu'il ne sert encore rien.
    served_commit text CHECK (served_commit IS NULL OR served_commit ~ '^[0-9a-f]{40}$'),
    -- Le code du refus, quand l'ordre n'a pas abouti. Court, sans caractère de contrôle :
    -- il vient d'un autre service et finira sur un écran.
    refusal text CHECK (refusal IS NULL
        OR (char_length(refusal) BETWEEN 1 AND 40 AND refusal ~ '^[a-z][a-z0-9_]*$')),
    acked_at timestamptz,
    -- Servi OU refusé, jamais les deux : l'écran lit l'un ou l'autre, et porter les deux
    -- le laisserait choisir lequel croire. Et aucun des deux sans la date de la réponse,
    -- sans quoi on ne saurait pas de quand date l'instantané.
    CONSTRAINT hosted_version_reponse_coherente CHECK (
        (served_commit IS NULL AND refusal IS NULL AND acked_at IS NULL)
        OR (acked_at IS NOT NULL AND NOT (served_commit IS NOT NULL AND refusal IS NOT NULL))
    )
);

COMMENT ON TABLE hosted_version IS
    'La version qu''un environnement doit servir, et ce qu''il a répondu quand on lui a '
    'poussé l''ordre. Le contenu, lui, vit dans git : cette table ne porte que le choix.';
