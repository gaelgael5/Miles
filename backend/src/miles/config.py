from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class Settings(BaseSettings):
    """Configuration du back-office, lue dans l'environnement (préfixe MILES_)."""

    # extra="forbid" : une clef mal orthographiée doit faire échouer le démarrage,
    # pas laisser silencieusement s'appliquer une valeur par défaut.
    model_config = SettingsConfigDict(env_prefix="MILES_", extra="forbid", frozen=True)

    # Obligatoire, sans défaut : un back-office démarré sans base n'a aucun sens,
    # et une URL par défaut pointerait en silence vers une base qui n'est pas la bonne.
    database_url: SecretStr
    db_pool_min_size: int = Field(default=1, ge=1)
    db_pool_max_size: int = Field(default=10, ge=1)
    db_connect_timeout_s: float = Field(default=5.0, gt=0)
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR
    log_level: Literal["debug", "info", "warning", "error"] = "info"
