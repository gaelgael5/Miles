-- L'ESPÈCE du demandeur : un environnement, ou le module de paramétrage (ticket ba44914b).
--
-- POURQUOI ELLE EST EN BASE ET PAS DÉDUITE. Accepter l'un ou l'autre n'a pas les mêmes
-- conséquences : un environnement reçoit des devices, le module de paramétrage se fait
-- confier des connexions git. L'humain qui accepte doit savoir ce qu'il accepte, et ce
-- qu'il a accepté doit rester lisible après coup — un appariement dont on ne saurait plus
-- l'espèce laisserait « pourquoi cette stack a-t-elle reçu ces secrets ? » sans réponse.
--
-- ELLE EST DÉCLARÉE PAR LE DEMANDEUR, DONC ELLE N'AUTORISE RIEN PAR ELLE-MÊME. Comme le
-- nom déclaré, elle arrive d'un tiers que personne n'a encore authentifié. Ce qu'elle fait,
-- c'est permettre à l'humain de LIRE ce qu'il s'apprête à accepter ; l'autorisation, c'est
-- son geste — révéler le code —, et les conséquences de l'espèce sont appliquées ensuite
-- depuis la valeur enregistrée ici.
--
-- LA TABLE S'APPELLE TOUJOURS `environment_peer`, ET CE N'EST PAS UN OUBLI. Elle porte
-- désormais les modules appariés, dont les environnements sont la première espèce et
-- resteront la plus nombreuse. La renommer coûterait une migration de renommage, la
-- réécriture de toutes ses requêtes, et surtout la rupture du genre d'objet `environment_peer`
-- des events déjà écrits : l'historique de chaque appariement se couperait en deux. Le gain
-- serait un nom plus juste ; le prix, un journal qu'on ne peut plus suivre. Le nom est donc
-- historique, et il est dit ici pour que personne ne le lise comme une erreur.

-- Ajoutée nullable, remplie, puis rendue obligatoire — jamais avec une valeur par défaut.
-- Un défaut ferait qu'un INSERT qui oublierait la colonne enregistrerait un environnement
-- en silence, et c'est exactement la décision qu'on veut rendre impossible à prendre sans
-- le dire. Même geste que l'adresse de contact à la migration 13.
ALTER TABLE pairing_request
    ADD COLUMN species text CHECK (species IN ('environnement', 'parametrage'));

ALTER TABLE environment_peer
    ADD COLUMN species text CHECK (species IN ('environnement', 'parametrage'));

-- Les lignes déjà en base sont des environnements, et ce n'est pas une supposition de
-- confort : avant ce ticket, aucune autre espèce ne pouvait frapper. C'est la seule valeur
-- qui soit vraie pour elles.
UPDATE pairing_request SET species = 'environnement' WHERE species IS NULL;
UPDATE environment_peer SET species = 'environnement' WHERE species IS NULL;

ALTER TABLE pairing_request
    ALTER COLUMN species SET NOT NULL;

ALTER TABLE environment_peer
    ALTER COLUMN species SET NOT NULL;

-- UN SEUL module de paramétrage apparié, tenu par le MODÈLE et pas seulement par l'écran
-- (critère 3 du ticket, et interdit explicite : « un modèle de données permettant plusieurs
-- modules de paramétrage appariés »). Arbitrage de Gael du 27/10/2026 : un-à-un.
--
-- Un index unique PARTIEL, et non une contrainte : l'unicité ne porte que sur une espèce.
-- Les environnements, eux, sont N par construction — c'est toute la raison d'être de ce
-- module. Unique sur `species` parmi les seules lignes de paramétrage, donc au plus une.
--
-- C'est la base qui tranche, pas une lecture préalable : entre un SELECT et un INSERT, deux
-- confirmations concurrentes passeraient toutes les deux. La seconde est refusée ici, et le
-- refus est traduit en mot lisible par le service.
CREATE UNIQUE INDEX environment_peer_un_seul_parametrage
    ON environment_peer (species) WHERE species = 'parametrage';

-- SEUL un environnement se rattache à un environnement du référentiel. Le module de
-- paramétrage ne reçoit pas de devices : lui désigner un environnement n'aurait aucun sens,
-- et le laisser possible ferait consommer — par l'unicité de `environment_id` — un
-- environnement qu'aucune stack ne servirait jamais.
--
-- Le code refuse déjà le geste en le NOMMANT, parce qu'un refus de contrainte n'explique
-- rien à qui le lit. Ces deux CHECK sont la garde qu'on n'oublie pas d'appeler : une
-- désignation posée par un chemin qu'on n'a pas prévu est refusée par la base.
ALTER TABLE pairing_request
    ADD CONSTRAINT pairing_request_environnement_seul_designe CHECK (
        species = 'environnement' OR environment_id IS NULL);

ALTER TABLE environment_peer
    ADD CONSTRAINT environment_peer_environnement_seul_rattache CHECK (
        species = 'environnement' OR environment_id IS NULL);
