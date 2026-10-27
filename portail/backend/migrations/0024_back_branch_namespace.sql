-- Les branches de Miles passent de « work/<nom> » à « back/<workspace>/<nom> » (Gael,
-- 24/10/2026). « work/ » ne disait pas à quel workspace une branche appartenait : sur la
-- forge, on lisait « work/atelier » sans savoir de qui. « back/ » les sépare des branches
-- humaines du dépôt, et le segment du workspace les isole les unes des autres.
--
-- L'ordre des trois temps n'est pas interchangeable : on LÂCHE les anciennes contraintes,
-- PUIS on réécrit, PUIS on pose les nouvelles. Réécrire d'abord échoue, l'ancienne
-- contrainte refusant la nouvelle forme — mesuré, pas supposé.
--
-- La nouvelle contrainte lie le nom au workspace de la ligne : une branche rangée sous un
-- autre workspace que le sien devient impossible à écrire.
--
-- ATTENTION — ce que SQL ne peut pas faire : les branches portent ces noms DANS LES DÉPÔTS
-- git, qui sont hors de Miles. Après cette migration, la base désigne « back/<ws>/<nom> »
-- tandis que la forge porte encore « work/<nom> » : chaque dépôt de paramétrage doit être
-- renommé en conséquence, sans quoi le workspace pointe une branche qui n'existe pas.
ALTER TABLE workspace_work_branches DROP CONSTRAINT workspace_work_branches_branch_check;
-- Nom relevé dans pg_constraint, pas déduit : portant sur deux colonnes, PostgreSQL la
-- nomme d'après la table seule, sans suffixe de colonne.
ALTER TABLE workspace_branches DROP CONSTRAINT workspace_branches_check;

UPDATE workspace_work_branches
SET branch = 'back/' || workspace_id || '/' || substring(branch from 6)
WHERE branch LIKE 'work/%';

UPDATE workspace_branches
SET branch = 'back/' || workspace_id || '/' || slug
WHERE branch LIKE 'work/%';

ALTER TABLE workspace_work_branches
    ADD CONSTRAINT workspace_work_branches_branch_check
    CHECK (branch ~ '^back/[a-z0-9][a-z0-9-]{1,62}/[a-z0-9][a-z0-9-]{0,39}$'
           AND branch LIKE 'back/' || workspace_id || '/%');

ALTER TABLE workspace_branches
    ADD CONSTRAINT workspace_branches_check
    CHECK (branch = 'back/' || workspace_id || '/' || slug);
