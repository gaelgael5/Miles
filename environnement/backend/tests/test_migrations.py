from __future__ import annotations

from miles_socle.db.migration_files import file_load_migrations

from environnement.config import DEFAULT_MIGRATIONS_DIR


def test_la_sequence_part_de_un_et_ne_saute_aucun_numero() -> None:
    # La séquence repart de 0001 : cette base n'a aucun historique commun avec celle du
    # portail, et un trou de numérotation ferait diverger deux installations.
    versions = [migration.version for migration in file_load_migrations(DEFAULT_MIGRATIONS_DIR)]

    assert versions == list(range(1, len(versions) + 1))


def test_toutes_les_tables_que_le_socle_interroge_sont_creees() -> None:
    """Le socle ne porte aucune MIGRATION : si le produit oublie une table, c'est 500.

    Le socle porte bien les requêtes de ses propres tables — secrets, sessions, journal,
    identité du module —, mais aucun schéma : celui de chaque produit est relu produit par
    produit. L'accord entre les deux n'est donc tenu que par ce test, et par PostgreSQL.

    Ce contrôle reste volontairement LOCAL au produit — il lit ses propres migrations et
    rien d'autre. Comparer le schéma de deux produits a été écarté le 27/10/2026 : l'écart
    entre produits est tenu par la revue humaine, pas par un test.
    """
    sql = "\n".join(migration.sql for migration in file_load_migrations(DEFAULT_MIGRATIONS_DIR))

    for table in (
        "events",
        "event_object_sequences",
        "event_objects",
        "cultures",
        "secrets",
        "secret_usages",
        "sessions",
        "oidc_connectors",
        "oidc_connector_labels",
        "oidc_login_attempts",
        "oidc_identities",
        "user_preferences",
        "module_identity",
        "enrolment_peer",
        "pairing_attempt",
    ):
        assert f"CREATE TABLE {table} (" in sql, f"table absente des migrations : {table}"


def test_le_repli_en_us_est_actif_et_la_base_refuse_de_le_desactiver() -> None:
    sql = "\n".join(migration.sql for migration in file_load_migrations(DEFAULT_MIGRATIONS_DIR))

    # Garde portée par la base elle-même, et non par le code : en-US est le repli de tout
    # libellé déclinable, et le désactiver casserait l'affichage de tous les connecteurs.
    assert "CONSTRAINT cultures_fallback_always_active CHECK (code <> 'en-US' OR active)" in sql
    assert "('en-US', 'English (United States)', 'English (United States)', true)" in sql
