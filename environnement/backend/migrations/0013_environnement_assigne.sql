-- L'environnement du référentiel auquel le module d'enrôlement nous a rattachés, et la
-- date à laquelle on l'a appris (ticket 2edf1f3c).
--
-- POURQUOI LE MÉMORISER PLUTÔT QUE DE L'AFFICHER À LA VOLÉE. Cette valeur vient d'un
-- autre module, par un appel signé. Une page qui ne s'affiche que si cet autre module
-- répond mentirait sur la nature de la panne : l'administrateur croirait son environnement
-- perdu alors qu'un réseau est coupé. La valeur mémorisée est un REPLI ASSUMÉ, et c'est
-- pour cela que sa date est stockée avec elle — un repli qui ne dit pas qu'il en est un
-- est indiscernable d'un bug.
--
-- POURQUOI SUR LA LIGNE DU PAIR, et pas dans une table à part. Ce rattachement n'existe
-- que par l'appariement : sans pair, il n'a pas de sens, et une table séparée permettrait
-- d'en garder un alors qu'aucun pair ne le revendique.
ALTER TABLE enrolment_peer
    -- Le slug et le libellé, jamais l'identifiant : celui-ci est la clé du référentiel de
    -- l'enrôlement, et le ranger ici écrirait une relation entre deux bases que personne
    -- ne réconcilie. Les deux sont nuls ENSEMBLE — « rattaché » est une seule information,
    -- et un slug sans libellé ne s'afficherait pas.
    ADD COLUMN environment_slug text,
    ADD COLUMN environment_label text,
    -- La date à laquelle NOUS avons reçu cette valeur, avec NOTRE horloge. Nulle tant
    -- qu'on n'a jamais réussi à la lire, et c'est l'état du premier jour.
    ADD COLUMN environment_fetched_at timestamptz,
    -- Les trois vont ensemble ou pas du tout : une date sans valeur ferait afficher un
    -- repli vide daté, et une valeur sans date la ferait passer pour fraîche. Ce que le
    -- code tient déjà, la base le refuse aussi — c'est la garde qu'on n'oublie pas.
    ADD CONSTRAINT enrolment_peer_environment_complet CHECK (
        (environment_slug IS NULL AND environment_label IS NULL
            AND environment_fetched_at IS NULL)
        OR (environment_slug IS NOT NULL AND environment_label IS NOT NULL
            AND environment_fetched_at IS NOT NULL)
    );

-- Rien à remplir : aucune valeur ne peut être devinée. Un environnement qu'on n'a jamais
-- lu chez le pair n'a pas de nom connu, et en inventer un — le nom déclaré de la stack,
-- par exemple — afficherait comme autorité un nom que personne n'a posé là-bas. C'est
-- justement la confusion que ce ticket corrige.
