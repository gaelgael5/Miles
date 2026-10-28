"""Configuration commune aux trois produits : la base qu'ils étendent.

Les trois portaient la même classe à deux lignes près. Le préfixe d'environnement,
`extra="forbid"`, les champs obligatoires sans défaut et les défauts de sécurité sont des
règles du socle, pas des choix de produit — et les voir recopiées trois fois, c'est voir
trois endroits où elles peuvent diverger. C'est déjà arrivé : le commentaire d'
`extra="forbid"` promettait une garantie fausse et avait été recopié dans un deuxième
produit AVANT d'être vérifié (LESSONS.md, 27/10/2026).

Ce que le produit garde : son répertoire de migrations — le socle n'en porte aucune et
n'a donc rien à dire de son emplacement — et ses propres champs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PUBLIC_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?/?$")


class SocleConfig(BaseSettings):
    """Les règles de lecture de la configuration, communes aux trois produits.

    Le préfixe est le même pour les trois, et c'est VOULU : chacun a son `.env`, monté dans
    son conteneur, et le socle impose les noms `MILES_ADMIN_*` du compte d'amorçage.
    L'étanchéité est portée par le fichier et la base, jamais par le nom de la variable.
    """

    # extra="forbid" : une clef inconnue fournie EN CODE est refusée. Attention à la portée
    # réelle — pydantic-settings ne confronte à cette règle que les sources qu'il énumère,
    # et l'environnement ne s'énumère pas (il porte PATH, HOME et le reste). Une variable
    # MILES_* mal orthographiée est donc IGNORÉE et le défaut s'applique : mesuré le
    # 27/10/2026, et tenu par un test qui dit la limite au lieu de la supposer absente. Une
    # liste blanche des MILES_* a été écartée, le préfixe portant aussi des valeurs qui ne
    # sont pas des champs ici (MILES_ADMIN_*, MILES_DB_PASSWORD…).
    # hide_input_in_errors : un démarrage refusé est journalisé, et l'erreur pydantic
    # recopierait sinon les valeurs lues — mots de passe et clé des secrets compris.
    model_config = SettingsConfigDict(
        env_prefix="MILES_", extra="forbid", frozen=True, hide_input_in_errors=True
    )


class SocleDatabaseSettings(SocleConfig):
    """Ce qu'il faut pour joindre la base et la migrer.

    Séparée de la configuration du service web : `<produit>-migrate` n'a pas à exiger le
    `.env` monté, qui ne concerne que le service web.

    Le répertoire des migrations n'est PAS ici : le socle n'en porte aucune, donc il n'a
    rien à dire de l'endroit où un produit range le sien. Chaque produit le déclare, avec
    son défaut.
    """

    # Obligatoire, sans défaut : un back-office démarré sans base n'a aucun sens, et une
    # URL par défaut pointerait en silence vers une base qui n'est pas la bonne.
    database_url: SecretStr
    db_pool_min_size: int = Field(default=1, ge=1)
    db_pool_max_size: int = Field(default=10, ge=1)
    db_connect_timeout_s: float = Field(default=5.0, gt=0)
    log_level: Literal["debug", "info", "warning", "error"] = "info"


class SocleWebSettings(SocleConfig):
    """Ce qu'il faut au service web : l'amorçage, la session, les secrets, l'adresse publique.

    Les champs obligatoires le sont par choix de sécurité, pas par oubli d'un défaut : voir
    le commentaire de chacun. En ajouter un défaut ferait démarrer un produit contre la
    mauvaise base, avec des secrets lisibles, ou en devinant si un administrateur existe.
    """

    # Le `.env` de l'hôte et sa sauvegarde, montés fichier par fichier : le compte
    # d'amorçage y vit (décision du 19/10/2026). Obligatoires : sans eux, le service ne
    # saurait pas si un administrateur existe, et il ne doit pas deviner.
    env_file: Path
    env_backup_file: Path
    session_ttl_s: int = Field(default=12 * 3600, gt=0)
    # Vrai par défaut : les produits sont servis en HTTPS par le relais. Le désactiver n'a
    # de sens que pour un accès HTTP direct, sur une machine de test.
    cookie_secure: bool = True
    # Clé qui chiffre les secrets de l'instance (MILES_SECRETS_KEY), générée une fois dans
    # `.env`. Obligatoire et sans défaut : une clé de secours rendrait les secrets lisibles
    # par quiconque connaît le code. Elle NE SE RÉGÉNÈRE JAMAIS — les secrets déjà chiffrés
    # en base deviendraient illisibles.
    secrets_key: SecretStr
    # Adresse publique du produit (https://…), d'où se déduit l'URL de retour OIDC.
    # Configurée, jamais lue des en-têtes de la requête : un Host forgé enverrait le code
    # d'autorisation ailleurs. Absente, la connexion OIDC est indisponible.
    public_url: str | None = None
    # Faux par défaut : un fournisseur d'identité (connecteur OIDC, service de sécurité) en
    # HTTP laisse passer jetons, codes et secrets en clair. Seuls les tests d'intégration,
    # contre des fournisseurs jetables, l'activent.
    allow_http_identity_providers: bool = False

    @field_validator("public_url")
    @classmethod
    def _public_url_shape(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        if not _PUBLIC_URL_RE.match(value):
            raise ValueError("public_url doit être une origine http(s) sans chemin")
        return value.rstrip("/")
