-- Le compte des items que le NETTOYAGE a supprimés à la fin d'un import (story 45543845).
--
-- Sur la ligne d'ingestion, et c'est le critère 8 : le journal des appels garde UNE ligne
-- par import, avec son compte de supprimés, là où le journal d'events en prend une par
-- item supprimé. Les deux sont nécessaires et ne se remplacent pas — l'un répond « cet
-- import a-t-il sorti des objets, et combien », l'autre « lesquels, et que portaient-ils ».
--
-- En colonne et non dans le compte-rendu `report` : le compte-rendu décrit le sort des
-- objets DU DÉPÔT, et un item supprimé n'en fait pas partie — il était déjà là, et c'est
-- une règle, pas le document, qui l'a désigné. Les mêler aurait fait répondre « reçus :
-- 1 000, supprimés : 12 » à un écran qui additionne des sorts d'objets déposés.
--
-- NULLABLE, et les deux cas que `NULL` recouvre sont dits ailleurs qu'ici : un import
-- antérieur à cette colonne, un import qui n'a pas nettoyé (mode synchrone, import
-- incomplet ou en échec), et un nettoyage REFUSÉ parce qu'une règle n'est plus évaluable
-- — ce dernier laisse son anomalie `nettoyage_refuse` dans le compte-rendu. Un défaut à
-- zéro aurait affirmé « rien à supprimer » dans les quatre cas.
ALTER TABLE ingestions ADD COLUMN items_removed integer
    CHECK (items_removed IS NULL OR items_removed >= 0);
