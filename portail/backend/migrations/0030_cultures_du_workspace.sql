-- Cultures du PARAMÉTRAGE d'un workspace (story 639c25da) : les langues dans lesquelles
-- on traduit ce que ce workspace décrit. Ce ne sont PAS les cultures actives de
-- l'application de configuration, qui sont les langues de l'OUTIL : deux workspaces du
-- même Miles peuvent viser des pays différents, et un exploitant qui lit le back-office
-- en français traduit un paramétrage en arabe et en thaï. Les deux listes n'ont aucune
-- raison d'être la même.
--
-- Une seule table pour les deux rôles, plutôt qu'une colonne sur `workspaces` et une
-- table d'additionnelles : la clé primaire rend alors structurellement impossible qu'une
-- culture soit à la fois la défaut et une additionnelle (critère 4), et changer la
-- culture par défaut devient un basculement de drapeau qui GARDE les valeurs déjà
-- saisies (critère 5) au lieu d'un déplacement entre deux tables.
CREATE TABLE workspace_cultures (
    workspace_id text NOT NULL REFERENCES workspaces (id) ON DELETE CASCADE,
    -- Le catalogue complet, jamais restreint aux cultures actives de l'application :
    -- traduire en thaï n'exige pas de lire le back-office en thaï (critère 9).
    culture text NOT NULL REFERENCES cultures (code),
    is_default boolean NOT NULL DEFAULT false,
    PRIMARY KEY (workspace_id, culture)
);

-- Une seule culture par défaut par workspace : l'index l'interdit, et le code n'a pas à
-- y penser au moment d'en basculer une autre.
CREATE UNIQUE INDEX workspace_cultures_one_default
    ON workspace_cultures (workspace_id)
    WHERE is_default;

-- Workspaces déjà créés : ils n'ont pas pu choisir, et la culture par défaut est
-- obligatoire (critère 1). en-US est le seul choix défendable — c'est la culture que la
-- base garantit active (contrainte cultures_fallback_always_active), donc la seule dont
-- on sait qu'elle existe sur toute installation. Elle se change ensuite comme n'importe
-- quelle culture par défaut, d'autant que leur référentiel de traductions est vide.
INSERT INTO workspace_cultures (workspace_id, culture, is_default)
SELECT id, 'en-US', true FROM workspaces;
