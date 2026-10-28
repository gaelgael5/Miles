from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from miles_socle.settings import SocleDatabaseSettings, SocleWebSettings
from miles_socle.testing import DSN, SECRETS_KEY

PRODUIT_MIGRATIONS = Path("/produit/migrations")


class DatabaseSettings(SocleDatabaseSettings):
    """Ce qu'un produit ajoute, et c'est tout : l'emplacement de SES migrations."""

    migrations_dir: Path = PRODUIT_MIGRATIONS


class Settings(SocleWebSettings, DatabaseSettings):
    """La composition que font les trois produits : le web, plus l'accès base."""


def _settings(**extra: object) -> Settings:
    return Settings(  # type: ignore[arg-type]
        database_url=DSN,
        env_file=Path("/run/miles/.env"),
        env_backup_file=Path("/run/miles/.env.bak"),
        secrets_key=SECRETS_KEY,
        **extra,
    )


def test_le_socle_ne_declare_pas_le_repertoire_des_migrations() -> None:
    # Le socle ne porte AUCUN SQL (décision du 27/10/2026) : il n'a donc rien à dire de
    # l'endroit où un produit range ses migrations. Si ce champ remontait au socle, il
    # faudrait lui donner un défaut, et ce défaut serait faux pour les trois produits.
    assert "migrations_dir" not in SocleDatabaseSettings.model_fields
    assert DatabaseSettings(database_url=DSN).migrations_dir == PRODUIT_MIGRATIONS


def test_la_composition_d_un_produit_porte_les_champs_des_deux_bases() -> None:
    champs = set(Settings.model_fields)

    assert {"database_url", "db_pool_max_size", "log_level"} <= champs
    assert {"env_file", "secrets_key", "cookie_secure", "public_url"} <= champs
    assert "migrations_dir" in champs


def test_un_champ_inconnu_passe_en_argument_est_refuse() -> None:
    # Ce que extra="forbid" garantit réellement : une clef inconnue fournie EN CODE est
    # refusée. Mesuré le 27/10/2026.
    with pytest.raises(ValidationError):
        SocleDatabaseSettings(database_url=DSN, db_pool_maxsize=20)  # type: ignore[call-arg]


def test_une_variable_d_environnement_mal_orthographiee_est_ignoree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Limite MESURÉE le 27/10/2026, pas un comportement voulu.

    pydantic-settings ne confronte à `extra="forbid"` que les clefs des sources qu'il
    énumère ; la source « environnement » ne s'énumère pas — l'environnement d'un conteneur
    contient PATH, HOME et tout le reste. Une variable MILES_* mal orthographiée est donc
    ignorée, et le défaut s'applique.

    Ce test existe pour que la limite soit écrite quelque part plutôt que supposée absente.
    Une garde par liste blanche des MILES_* a été écartée : le même préfixe porte aussi des
    valeurs qui ne sont pas des champs ici (MILES_ADMIN_*, MILES_DB_PASSWORD, MILES_HTTP_PORT).
    Elle est au socle désormais, donc dite une fois pour les trois produits — avant, le
    commentaire qui la niait avait été recopié dans un deuxième produit sans être vérifié.
    """
    monkeypatch.setenv("MILES_DATABASE_URL", DSN)
    monkeypatch.setenv("MILES_DB_POOL_MAXSIZE", "20")

    assert SocleDatabaseSettings().db_pool_max_size == 10  # type: ignore[call-arg]


def test_une_base_absente_fait_echouer_le_demarrage() -> None:
    # Sans défaut, et c'est voulu : une URL par défaut pointerait en silence vers une base
    # qui n'est pas la bonne.
    with pytest.raises(ValidationError):
        SocleDatabaseSettings()  # type: ignore[call-arg]


@pytest.mark.parametrize("champ", ["env_file", "env_backup_file", "secrets_key"])
def test_les_champs_obligatoires_du_service_web_le_restent(champ: str) -> None:
    # Chacun est un choix de sécurité : sans `.env` le service ne saurait pas si un
    # administrateur existe, et une clé de secours rendrait les secrets lisibles.
    assert SocleWebSettings.model_fields[champ].is_required()


def test_les_defauts_de_securite_sont_fermes() -> None:
    settings = _settings()

    # Cookie sécurisé, et aucun fournisseur d'identité en HTTP : les deux sont des gardes,
    # pas des préférences. Un socle qui les ouvrirait ouvrirait les trois produits.
    assert settings.cookie_secure is True
    assert settings.allow_http_identity_providers is False
    # Session de douze heures, pas infinie.
    assert settings.session_ttl_s == 12 * 3600


def test_l_adresse_publique_doit_etre_une_origine_sans_chemin() -> None:
    with pytest.raises(ValidationError):
        _settings(public_url="https://miles.example.org/chemin")


def test_l_adresse_publique_vide_vaut_absente() -> None:
    # Absente, la connexion OIDC est indisponible — ce qui vaut mieux qu'une URL de retour
    # fausse, vers laquelle le fournisseur enverrait le code d'autorisation.
    assert _settings(public_url="  ").public_url is None
    assert _settings().public_url is None


def test_l_adresse_publique_perd_son_slash_final() -> None:
    assert _settings(public_url="https://miles.example.org/").public_url == (
        "https://miles.example.org"
    )


def test_la_configuration_ne_laisse_pas_fuir_les_secrets_dans_sa_representation() -> None:
    # Un démarrage refusé est journalisé : ni l'URL de base ni la clé des secrets ne
    # doivent apparaître dans la représentation de la configuration.
    texte = repr(_settings())

    assert "x@db" not in texte
    assert SECRETS_KEY not in texte


def test_la_configuration_est_figee() -> None:
    # `frozen` : une configuration modifiée en cours de route ferait diverger ce que lisent
    # deux services câblés à des instants différents.
    settings = _settings()

    with pytest.raises(ValidationError):
        settings.cookie_secure = False  # type: ignore[misc]
