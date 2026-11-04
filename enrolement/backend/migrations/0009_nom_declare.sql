-- Le nom qu'un environnement déclare en frappant (ticket ce66f5bb) : ce qui permet à un
-- humain, devant la liste des demandes, de reconnaître celle qu'il accepte.
--
-- NULLABLE, et ce n'est pas un relâchement : la colonne arrive après que des appariements
-- ont pu être conclus sans elle, et une colonne obligatoire exigerait d'inventer une
-- valeur pour ces lignes-là. NULL dit « cet appariement est antérieur au nom déclaré »,
-- ce qu'aucune chaîne vide ne saurait dire sans mentir. L'API, elle, l'exige pour toute
-- NOUVELLE demande — la contrainte est là où la donnée entre, pas sur l'histoire.
--
-- Le CHECK ne retire rien du contenu : il borne la longueur et refuse les caractères de
-- contrôle, qui cassent une ligne de journal structuré. L'échappement appartient à
-- l'affichage, qui seul sait dans quel contexte il écrit.
ALTER TABLE pairing_request
    ADD COLUMN name text CHECK (name IS NULL OR (char_length(name) BETWEEN 1 AND 80
        AND name !~ '[[:cntrl:]]'));

ALTER TABLE environment_peer
    ADD COLUMN name text CHECK (name IS NULL OR (char_length(name) BETWEEN 1 AND 80
        AND name !~ '[[:cntrl:]]'));
