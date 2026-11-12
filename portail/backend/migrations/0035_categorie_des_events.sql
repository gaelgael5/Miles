-- La catégorie de l'event : QUI l'introduit, et donc qui peut l'éditer dans l'IHM de
-- configuration. Huitième et dernier champ de la racine commune à recevoir sa colonne
-- (décision de Gael du 12/11/2026 : « on introduit une notion de catégorie pour
-- identifier qui introduit l'event », et « on reste sur les numéros »).
--
-- POURQUOI MAINTENANT, et pas avec les trois autres champs de la racine le même jour :
-- la valeur ne devient calculable que lorsque le catalogue de types déclare la catégorie
-- de CHAQUE type. Tant qu'un seul des trois produits n'avait pas basculé, la colonne
-- n'aurait pu être que nullable — et une catégorie nulle laisse l'IHM de configuration
-- sans son verrou de lecture seule, c'est-à-dire sans la décision qu'elle applique.
--
-- `smallint` : les numéros sont stables et il y en a sept. `NOT NULL` : un event sans
-- catégorie n'existe pas, puisque le catalogue l'exige de chaque type déclaré.
--
-- PAS de CHECK énumérant les sept numéros, et c'est délibéré. La liste des catégories
-- n'est PAS close — « je ne sais pas si les catégories sont au complet, probablement
-- pas » —, et une borne haute en base obligerait à une migration par catégorie ajoutée.
-- Le jour où l'on oublierait cette migration, les écritures tomberaient en production
-- sur une violation de contrainte, loin de leur cause. La borne basse, elle, est un vrai
-- invariant : les numéros sont des rangs, jamais négatifs. Le refus d'un numéro inconnu
-- est tenu par le code, qui le NOMME (`events.categories.of_number`).
ALTER TABLE events ADD COLUMN category smallint NOT NULL DEFAULT 0
    CHECK (category >= 0);

-- Le défaut n'a servi qu'à remplir les lignes existantes, et il s'en va : le laisser
-- ferait entrer une catégorie plausible le jour où le producteur oublierait de la poser,
-- et un repli silencieux est exactement ce que cette colonne doit empêcher. La valeur
-- choisie pour les lignes anciennes n'est pas une approximation : tous les types déclarés
-- par ce produit à ce jour sont introduits par son propre back-office, donc 0
-- (backoffice-configuration) est la catégorie EXACTE de chaque event déjà écrit ici.
ALTER TABLE events ALTER COLUMN category DROP DEFAULT;

COMMENT ON COLUMN events.category IS
    'Qui introduit ce type d''event (backoffice-configuration pour les events déjà écrits). '
    'Numéro stable, défini par miles_socle.events.categories ; '
    'un type introduit par du code est en lecture seule dans l''IHM de configuration.';
