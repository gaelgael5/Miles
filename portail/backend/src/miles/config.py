from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PUBLIC_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?/?$")
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class DatabaseSettings(BaseSettings):
    """Ce qu'il faut pour joindre la base et la migrer (préfixe MILES_).

    Séparée de Settings : `miles-migrate` n'a pas à exiger le .env monté, qui ne
    concerne que le service web.
    """

    # extra="forbid" : une clef mal orthographiée doit faire échouer le démarrage,
    # pas laisser silencieusement s'appliquer une valeur par défaut.
    # hide_input_in_errors : un démarrage refusé est journalisé, et l'erreur pydantic
    # recopierait sinon les valeurs lues — mots de passe et clé des secrets compris.
    model_config = SettingsConfigDict(
        env_prefix="MILES_", extra="forbid", frozen=True, hide_input_in_errors=True
    )

    # Obligatoire, sans défaut : un back-office démarré sans base n'a aucun sens,
    # et une URL par défaut pointerait en silence vers une base qui n'est pas la bonne.
    database_url: SecretStr
    db_pool_min_size: int = Field(default=1, ge=1)
    db_pool_max_size: int = Field(default=10, ge=1)
    db_connect_timeout_s: float = Field(default=5.0, gt=0)
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR
    log_level: Literal["debug", "info", "warning", "error"] = "info"


class Settings(DatabaseSettings):
    """Configuration du service web : la base, plus l'authentification."""

    # Le .env de l'hôte et sa sauvegarde, montés fichier par fichier : le compte
    # d'amorçage y vit (décision du 19/10/2026). Obligatoires : sans eux, le
    # service ne saurait pas si un administrateur existe, et ne doit pas deviner.
    env_file: Path
    env_backup_file: Path
    session_ttl_s: int = Field(default=12 * 3600, gt=0)
    # Vrai par défaut : le portail est servi en HTTPS par le relais. Le désactiver
    # n'a de sens que pour un accès HTTP direct, sur une machine de test.
    cookie_secure: bool = True
    # Broker MQTT 5. Obligatoire : un back-office qui ne sert pas les terminaux ne
    # doit pas démarrer en silence comme s'il était complet.
    mqtt_host: str
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str = "miles-backend"
    mqtt_password: SecretStr
    # Clé qui chiffre les secrets de l'instance (MILES_SECRETS_KEY), générée une fois
    # dans .env. Obligatoire et sans défaut : une clé de secours rendrait les secrets
    # lisibles par quiconque connaît le code.
    secrets_key: SecretStr
    # Adresse publique du portail (https://…), d'où se déduit l'URL de retour OIDC.
    # Configurée, jamais lue des en-têtes de la requête : un Host forgé enverrait le
    # code d'autorisation ailleurs. Absente, la connexion OIDC est indisponible.
    public_url: str | None = None
    # Faux par défaut : un fournisseur d'identité (connecteur OIDC, service de sécurité)
    # en HTTP laisse passer jetons, codes et secrets en clair. Seuls les tests
    # d'intégration, contre des fournisseurs jetables, l'activent.
    allow_http_identity_providers: bool = False
    # Hôtes git admis en plus de github.com (GitHub seul au premier lot). Vide en
    # production ; seuls les tests d'intégration y mettent leur forge jetable.
    git_test_hosts: list[str] = Field(default_factory=list)
    # Volume des copies de travail persistantes, une par branche (Gael, 22/10/2026).
    # Obligatoire : un dossier de secours dans le conteneur serait perdu au redéploiement
    # sans que rien ne le signale. Git fait foi, ce volume n'est qu'un cache.
    workcopies_dir: Path
    # Nombre de nœuds qu'une évaluation de template peut parcourir (MILES_TRANSFORM_BUDGET).
    # Le langage n'a pas de boucle, mais `$source` itère sur les données : la borne
    # interrompt un template lancé sur un document démesuré (ticket 68cae2ff).
    transform_budget: int = Field(default=100_000, gt=0)

    @field_validator("public_url")
    @classmethod
    def _public_url_shape(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        if not _PUBLIC_URL_RE.match(value):
            raise ValueError("public_url doit être une origine http(s) sans chemin")
        return value.rstrip("/")
