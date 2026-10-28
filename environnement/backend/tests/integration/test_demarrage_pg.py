from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.db.migration_files import file_load_migrations

from environnement.app import create_app
from environnement.config import DEFAULT_MIGRATIONS_DIR
from tests.conftest import SECRETS_KEY
from tests.integration.environnement_stack import ADMIN_USERNAME, admin_env, write_env

pytestmark = pytest.mark.integration


async def test_le_demarrage_n_exige_aucune_table_du_produit(
    blank_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le démarrage doit aboutir sur une base VIERGE, migrations non encore jouées.

    Reproduit une panne mesurée sur machine de test le 28/10/2026, au commit e9bd8f1 :
    la durée de vie de l'application engendrait l'identité du module au démarrage. Or
    `dev-deploy.sh` lance la stack PUIS joue les migrations — sur une base neuve, aucune
    table n'existe quand le backend démarre. Il tombait donc en boucle de redémarrage, et
    son redémarrage tuait la commande de migration lancée dans son conteneur : le schéma
    restait à 7, et le déploiement échouait sur un message qui ne nommait pas la cause
    (`relation "module_identity" does not exist`, visible seulement dans les logs du
    conteneur).

    Ce test est la garde contre la récidive, et elle vaut pour TOUT composant ajouté
    demain à la durée de vie de l'application, pas seulement pour l'identité.
    """
    env, backup = write_env(tmp_path, admin_env("admin@environnement.invalid"))
    monkeypatch.setenv("MILES_DATABASE_URL", blank_db)
    monkeypatch.setenv("MILES_ENV_FILE", str(env))
    monkeypatch.setenv("MILES_ENV_BACKUP_FILE", str(backup))
    monkeypatch.setenv("MILES_SECRETS_KEY", SECRETS_KEY)

    app = create_app()

    async with app.router.lifespan_context(app):
        rapport = await app.state.health_probe()

    # Démarré, et honnête sur son état : le schéma est en retard, la santé le dit, et
    # c'est ce verdict que le déploiement lit pour refuser de se déclarer bon.
    assert rapport.database_reachable
    assert rapport.schema_version is None
    assert not rapport.healthy
    # Déduite des fichiers de migration, jamais écrite en dur : un nombre figé ici
    # rougirait à la migration suivante sur un message qui ne parle pas de ce qu'il mesure.
    attendue = file_load_migrations(DEFAULT_MIGRATIONS_DIR)[-1].version
    assert rapport.expected_schema_version == attendue


async def test_le_compte_d_amorcage_est_lu_avant_toute_base(
    blank_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ce que le démarrage exige VRAIMENT : le .env, lu sur le disque. Un compte partiel
    # ou un fichier illisible doit empêcher le démarrage — fail closed — alors qu'une
    # base en retard, non : elle se rattrape par la migration qui suit.
    env, backup = write_env(tmp_path, admin_env("admin@environnement.invalid"))
    monkeypatch.setenv("MILES_DATABASE_URL", blank_db)
    monkeypatch.setenv("MILES_ENV_FILE", str(env))
    monkeypatch.setenv("MILES_ENV_BACKUP_FILE", str(backup))
    monkeypatch.setenv("MILES_SECRETS_KEY", SECRETS_KEY)

    app = create_app()

    async with app.router.lifespan_context(app):
        compte = app.state.auth.store.account

    assert compte is not None
    assert compte.username == ADMIN_USERNAME
