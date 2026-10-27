from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from enrolement.config import DEFAULT_MIGRATIONS_DIR, DatabaseSettings, Settings
from tests.conftest import DSN, SECRETS_KEY


def test_les_migrations_par_defaut_sont_celles_du_produit() -> None:
    # Le socle ne porte aucun SQL : c'est ce répertoire-ci qui fait foi, et il doit
    # exister dans l'image comme dans le dépôt.
    assert DEFAULT_MIGRATIONS_DIR.name == "migrations"
    assert (DEFAULT_MIGRATIONS_DIR / "0001_socle.sql").is_file()


def test_un_champ_inconnu_passe_en_argument_est_refuse() -> None:
    # Ce que extra="forbid" garantit réellement : une clef inconnue fournie EN CODE est
    # refusée. Mesuré le 27/10/2026.
    with pytest.raises(ValidationError):
        DatabaseSettings(database_url=DSN, db_pool_maxsize=20)  # type: ignore[call-arg]


def test_une_variable_d_environnement_mal_orthographiee_est_ignoree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Limite connue et mesurée, pas un comportement voulu.

    pydantic-settings ne confronte à `extra="forbid"` que les clefs des sources qu'il
    énumère ; la source « environnement » ne s'énumère pas — l'environnement d'un
    conteneur contient PATH, HOME et tout le reste. Une variable MILES_* mal
    orthographiée est donc ignorée, et le défaut s'applique.

    Ce test existe pour que la limite soit écrite quelque part plutôt que supposée
    absente : une garde par liste blanche des MILES_* a été écartée, le même préfixe
    portant aussi des valeurs qui ne sont pas des champs de cette classe
    (MILES_ADMIN_*, MILES_DB_PASSWORD, MILES_HTTP_PORT).
    """
    monkeypatch.setenv("MILES_DATABASE_URL", DSN)
    monkeypatch.setenv("MILES_DB_POOL_MAXSIZE", "20")

    settings = DatabaseSettings()  # type: ignore[call-arg]

    assert settings.db_pool_max_size == 10


def test_une_base_absente_fait_echouer_le_demarrage() -> None:
    with pytest.raises(ValidationError):
        DatabaseSettings()  # type: ignore[call-arg]


def test_l_adresse_publique_doit_etre_une_origine_sans_chemin(env_files: tuple[Path, Path]) -> None:
    env, backup = env_files

    with pytest.raises(ValidationError):
        Settings(  # type: ignore[arg-type]
            database_url=DSN,
            env_file=env,
            env_backup_file=backup,
            secrets_key=SECRETS_KEY,
            public_url="https://enrolement.example.org/chemin",
        )


def test_l_adresse_publique_vide_vaut_absente(env_files: tuple[Path, Path]) -> None:
    env, backup = env_files

    settings = Settings(  # type: ignore[arg-type]
        database_url=DSN,
        env_file=env,
        env_backup_file=backup,
        secrets_key=SECRETS_KEY,
        public_url="  ",
    )

    # Absente, la connexion OIDC est indisponible — ce qui vaut mieux qu'une URL de
    # retour fausse, vers laquelle le fournisseur enverrait le code d'autorisation.
    assert settings.public_url is None


def test_l_adresse_publique_perd_son_slash_final(env_files: tuple[Path, Path]) -> None:
    env, backup = env_files

    settings = Settings(  # type: ignore[arg-type]
        database_url=DSN,
        env_file=env,
        env_backup_file=backup,
        secrets_key=SECRETS_KEY,
        public_url="https://enrolement.example.org/",
    )

    assert settings.public_url == "https://enrolement.example.org"


def test_les_fournisseurs_en_http_sont_refuses_par_defaut(settings: Settings) -> None:
    # Un fournisseur d'identité en HTTP laisse passer jetons, codes et secrets en clair.
    assert settings.allow_http_identity_providers is False


def test_le_cookie_de_session_est_securise_par_defaut(settings: Settings) -> None:
    assert settings.cookie_secure is True


def test_la_configuration_ne_laisse_pas_fuir_les_secrets_dans_sa_representation(
    settings: Settings,
) -> None:
    # Un démarrage refusé est journalisé : ni l'URL de base ni la clé des secrets ne
    # doivent apparaître dans la représentation de la configuration.
    texte = repr(settings)

    assert "x@db" not in texte
    assert SECRETS_KEY not in texte
