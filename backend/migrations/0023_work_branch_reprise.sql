-- Reprise d'une branche existante (Gael, 23/10/2026) : en recâblant un workspace sur un
-- nouvel environnement, la branche de travail existe déjà dans le dépôt. L'ouverture la
-- refusait sans recours ; elle propose désormais de la reprendre, et le journal doit
-- distinguer ce cas d'une création — sinon on ne sait plus, après coup, si Miles a créé
-- la branche ou s'est branché sur une branche qui préexistait.
-- Additif : la contrainte s'élargit, aucune ligne existante n'est touchée.
ALTER TABLE workspace_work_branches DROP CONSTRAINT workspace_work_branches_outcome_check;
ALTER TABLE workspace_work_branches
    ADD CONSTRAINT workspace_work_branches_outcome_check
    CHECK (outcome IN ('initialisee', 'conforme', 'reprise'));
