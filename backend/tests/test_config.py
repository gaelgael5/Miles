from __future__ import annotations

import pytest
from pydantic import ValidationError

from miles.config import Settings

DSN = "postgresql://miles:s3cr3t-valeur@db:5432/miles"
FILES = {
    "env_file": "/run/miles/.env",
    "env_backup_file": "/run/miles/.env.bak",
    "workcopies_dir": "/var/lib/miles/workcopies",
    "mqtt_host": "mqtt",
    "mqtt_password": "mqtt-s3cr3t",
    "secrets_key": "cle-des-secrets-s3cr3t",
}


def test_settings_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MILES_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings()  # type: ignore[call-arg]


def test_settings_unknown_key_raises() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Settings(database_url=DSN, db_pool_size=5, **FILES)  # type: ignore[arg-type, call-arg]


def test_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MILES_DATABASE_URL", DSN)
    monkeypatch.setenv("MILES_DB_POOL_MAX_SIZE", "4")
    monkeypatch.setenv("MILES_ENV_FILE", "/run/miles/.env")
    monkeypatch.setenv("MILES_ENV_BACKUP_FILE", "/run/miles/.env.bak")
    monkeypatch.setenv("MILES_WORKCOPIES_DIR", "/var/lib/miles/workcopies")
    monkeypatch.setenv("MILES_MQTT_HOST", "mqtt")
    monkeypatch.setenv("MILES_MQTT_PASSWORD", "mqtt-s3cr3t")
    monkeypatch.setenv("MILES_SECRETS_KEY", "cle-des-secrets-s3cr3t")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.database_url.get_secret_value() == DSN
    assert settings.db_pool_max_size == 4
    assert settings.cookie_secure is True


def test_settings_missing_env_file_raises() -> None:
    with pytest.raises(ValidationError, match="env_file"):
        Settings(database_url=DSN)  # type: ignore[arg-type, call-arg]


def test_settings_repr_masks_database_url() -> None:
    settings = Settings(database_url=DSN, **FILES)  # type: ignore[arg-type]

    assert "s3cr3t-valeur" not in repr(settings)
    assert "mqtt-s3cr3t" not in repr(settings)
    assert "cle-des-secrets-s3cr3t" not in repr(settings)
    assert "s3cr3t-valeur" not in str(settings.model_dump())


def test_settings_invalid_log_level_raises() -> None:
    with pytest.raises(ValidationError, match="log_level"):
        Settings(database_url=DSN, log_level="verbose", **FILES)  # type: ignore[arg-type]


def test_settings_validation_error_never_echoes_the_values_it_read() -> None:
    # Un démarrage refusé s'écrit dans les journaux : l'erreur ne doit recopier
    # aucune des valeurs lues, mot de passe ou clé compris.
    files = {k: v for k, v in FILES.items() if k != "env_file"}
    with pytest.raises(ValidationError) as caught:
        Settings(database_url=DSN, **files)  # type: ignore[arg-type, call-arg]

    text = str(caught.value)
    assert "env_file" in text
    for value in (DSN, "mqtt-s3cr3t", "cle-des-secrets-s3cr3t"):
        assert value not in text
