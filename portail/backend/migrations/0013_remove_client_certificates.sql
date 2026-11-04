-- Retrait des certificats clients mTLS (Gael, 21/10/2026, story 6ea31024) : GitHub
-- n'accepte aucun certificat client sur HTTPS, et Miles ne parle à git qu'en HTTPS.
-- Une connexion s'authentifie désormais par son PAT, obligatoire.

-- Une connexion à certificat seul perdrait tout accès : on refuse de passer plutôt que
-- de la vider en silence, et on la nomme pour que l'administrateur lui donne un PAT.
DO $$
DECLARE
    without_token text;
BEGIN
    SELECT string_agg(id, ', ' ORDER BY id) INTO without_token
    FROM git_connections WHERE token_secret_slug IS NULL;
    IF without_token IS NOT NULL THEN
        RAISE EXCEPTION 'connexions git sans PAT, à compléter avant cette migration : %',
            without_token;
    END IF;
END $$;

ALTER TABLE git_connections
    DROP CONSTRAINT git_connections_access_declared,
    DROP COLUMN certificate_id,
    ALTER COLUMN token_secret_slug SET NOT NULL;

DROP TABLE client_certificates;

-- Les clés privées ne servaient qu'aux certificats retirés : les garder laisserait des
-- secrets d'un type que plus rien n'accepte ni ne sait supprimer par l'écran.
DELETE FROM secret_usages WHERE consumer_kind = 'client_certificate';
DELETE FROM secrets WHERE secret_type = 'GIT_CLIENT_KEY';
