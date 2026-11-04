-- Le référentiel des environnements du module d'enrôlement (ticket 2ea50d40).
--
-- POURQUOI CETTE TABLE EXISTE. Jusqu'ici, ce module ne savait pas NOMMER un
-- environnement : il connaissait des appariements, repérés par une URL et portant un
-- « nom déclaré » qu'un tiers non authentifié avait écrit. « Affecter un device à un
-- environnement » n'avait donc pas de sujet. C'est lui qu'on pose ici, et rien d'autre :
-- ni branche git, ni groupe applicatif, ni pointeur de version — cette part est suspendue
-- depuis le 26/10/2026, une stack étant construite depuis un commit et ne portant qu'une
-- version.
CREATE TABLE environment (
    -- Un identifiant STABLE, parce que le slug est renommable (arbitrage de Gael du
    -- 28/10/2026). Ce que l'appariement référence, ce que le journal nomme et ce qu'un
    -- device portera un jour doit survivre à une correction de faute de frappe.
    id uuid PRIMARY KEY,
    -- L'identifiant qui s'écrit : dans une adresse, un journal, une procédure. UNIQUE, et
    -- c'est la base qui le tient — jamais une lecture préalable, entre laquelle et
    -- l'écriture deux appels concurrents passent tous les deux.
    slug text NOT NULL UNIQUE
        CHECK (slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$' AND char_length(slug) BETWEEN 1 AND 48),
    -- Le libellé qui se lit. Le CHECK ne retire rien du contenu : il borne la longueur et
    -- refuse les caractères de contrôle, qui cassent une ligne de journal structuré.
    -- L'échappement appartient à l'affichage, qui seul sait dans quel contexte il écrit.
    label text NOT NULL
        CHECK (char_length(label) BETWEEN 1 AND 80 AND label !~ '[[:cntrl:]]'),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

-- Le lien vers l'appariement. NULLABLE à double titre : des appariements existent déjà
-- sans environnement — ils seront signalés « à rattacher » (ticket bf2115cd) —, et un
-- environnement déclaré mais pas encore apparié est l'état normal du premier jour.
--
-- Ce ticket CRÉE la colonne sans la remplir : c'est le geste de désignation qui la
-- remplira. Elle est ici parce que, sans elle, le référentiel ne peut pas répondre à
-- « puis-je supprimer cet environnement ? », et qu'une suppression sans garde installe
-- une habitude qu'il faudrait ensuite retirer.
ALTER TABLE environment_peer
    -- RESTRICT et non CASCADE : supprimer un environnement ne doit JAMAIS détruire un
    -- appariement au passage. Deux gestes qui n'ont pas les mêmes conséquences ne
    -- s'enchaînent pas tout seuls — on révoque d'abord, explicitement.
    ADD COLUMN environment_id uuid REFERENCES environment (id) ON DELETE RESTRICT,
    -- Un environnement porte AU PLUS un appariement, et c'est une contrainte du modèle.
    -- Deux stacks appariées pour un même environnement, et « à quelle stack appartient ce
    -- device » n'a plus de réponse unique. PostgreSQL admet plusieurs NULL sous un UNIQUE :
    -- les appariements pas encore rattachés ne se gênent donc pas entre eux.
    ADD CONSTRAINT environment_peer_environment_unique UNIQUE (environment_id);
