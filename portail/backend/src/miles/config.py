from __future__ import annotations

from pathlib import Path

from miles_socle.settings import SocleDatabaseSettings, SocleWebSettings
from pydantic import Field, SecretStr

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class DatabaseSettings(SocleDatabaseSettings):
    """Ce qu'il faut pour joindre la base et la migrer, plus le répertoire des migrations.

    Le socle ne porte **aucune migration** (décision du 27/10/2026) : il n'a rien à dire de
    l'endroit où ce produit range ses migrations, et ce champ reste ici avec son défaut.
    Tout le reste — préfixe `MILES_`, `extra="forbid"`, accès base, niveau de journal —
    vient du socle, où il est écrit une fois pour les trois produits.
    """

    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR


class Settings(SocleWebSettings, DatabaseSettings):
    """Configuration du portail : celle du socle, plus ce qui n'appartient qu'à lui.

    L'amorçage, la session, les secrets, l'adresse publique et le refus des fournisseurs
    d'identité en HTTP viennent du socle. Ne figurent ici que les réglages du module de
    paramétrage : le courtier MQTT, les copies de travail git, la borne d'évaluation des
    templates. Aucun champ du socle n'est redéclaré — le jour où il faudrait le faire,
    c'est au socle qu'il faut changer quelque chose.
    """

    # Broker MQTT 5. Obligatoire : un back-office qui ne sert pas les terminaux ne
    # doit pas démarrer en silence comme s'il était complet.
    mqtt_host: str
    mqtt_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_username: str = "miles-backend"
    mqtt_password: SecretStr
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
