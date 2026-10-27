-- Socle : horodatages en UTC pour toute session sur cette base.
-- Les journaux partitionnés à la journée et les dates de dernière écriture des
-- référentiels se comparent entre installations : un fuseau de session variable
-- déplacerait les frontières de partition.
DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'UTC');
END
$$;
