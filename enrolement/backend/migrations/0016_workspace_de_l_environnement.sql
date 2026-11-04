-- Le workspace placé sur un environnement (demande de Gael du 01/11/2026).
--
-- POURQUOI SUR L'ENVIRONNEMENT ET NON SUR L'APPARIEMENT. C'est l'environnement qui
-- héberge le paramétrage d'un workspace, et il le garde quand sa stack est révoquée puis
-- réappariée : porter ce choix sur `environment_peer` le ferait disparaître à chaque
-- révocation, et il faudrait le refaire sans que rien ne dise qu'il a été perdu.
--
-- Nullable : un environnement sans workspace est l'état normal tant qu'on ne lui en a pas
-- placé. Pas d'UNIQUE : deux environnements peuvent héberger le MÊME workspace — c'est
-- même le cas courant, une recette et une production servant le même paramétrage à des
-- versions différentes.
ALTER TABLE environment
    -- Le MÊME CHECK que `confided_git_workspace.id`, et pour cause : la seule source de
    -- cette valeur est la liste que le module de paramétrage nous confie. Une forme plus
    -- stricte ici refuserait un identifiant que le pair nous a pourtant transmis, et le
    -- refus serait incompréhensible côté écran.
    ADD COLUMN workspace_id text
        CHECK (workspace_id IS NULL
            OR (char_length(workspace_id) BETWEEN 1 AND 200 AND workspace_id !~ '[[:cntrl:]]'));
