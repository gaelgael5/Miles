-- Ce que l'environnement déclare en frappant, et ce qu'il doit retenir de sa demande
-- (tickets 29d05f91 et ce66f5bb).
--
-- `name` : le nom sous lequel CE module se présente au module d'enrôlement, saisi par un
-- administrateur sur l'écran d'appariement. Il ne l'identifie pas — c'est du texte libre
-- qui sert à ce qu'un humain, à l'autre bout, reconnaisse la demande qu'il accepte.
--
-- `expires_at` : l'échéance que le module d'enrôlement a annoncée en accusant la demande.
-- Elle est ici parce que c'est elle qui permet de distinguer REFUSÉE d'EXPIRÉE : le pair
-- ne garde aucune trace d'une demande disparue, et répond seulement « inconnue ». Inconnue
-- avant l'échéance, un humain a refusé ; inconnue après, elle a expiré. Sans cette
-- colonne, l'écran ne saurait dire laquelle des deux, et ferait recommencer à l'aveugle.
--
-- Les deux sont NULLABLE : la table existe depuis la migration précédente et pourrait
-- porter une tentative ouverte avant elles. NULL dit « on ne sait pas », ce qu'une valeur
-- inventée ne dirait pas.
ALTER TABLE pairing_attempt
    ADD COLUMN name text CHECK (name IS NULL OR (char_length(name) BETWEEN 1 AND 80
        AND name !~ '[[:cntrl:]]')),
    ADD COLUMN expires_at timestamptz;

-- Le nom que CE module a déclaré lors de l'appariement courant — pas celui du pair, qui
-- n'en déclare aucun. L'écran l'affiche pour que l'administrateur sache sous quel nom son
-- environnement est connu à l'autre bout, et puisse le retrouver dans leur liste.
ALTER TABLE enrolment_peer
    ADD COLUMN declared_name text CHECK (declared_name IS NULL
        OR (char_length(declared_name) BETWEEN 1 AND 80 AND declared_name !~ '[[:cntrl:]]'));
