from __future__ import annotations

from pathlib import Path

from miles_socle.settings import SocleDatabaseSettings, SocleWebSettings
from pydantic import Field

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
    """Configuration du service web : la base, l'authentification, et l'arbre servi.

    Tout vient du socle sauf le volume de l'arbre, qui n'a de sens que pour ce produit :
    lui seul SERT un paramétrage.
    """

    # Où vit l'arbre du paramétrage servi (story 3bbd4f87). AVEC UN DÉFAUT, et non exigé :
    # le paramétrage est dans git et l'enrôlement peut le repousser à tout moment, donc ce
    # répertoire se reconstitue. Refuser de démarrer toute la stack — appariement et
    # identité comprises — parce qu'un volume n'est pas déclaré rendrait indisponible ce
    # qui n'a pas besoin de lui. Volume non monté : l'arbre vit dans le conteneur et part
    # au redéploiement, et il suffit alors de renvoyer l'ordre.
    hosting_tree_dir: Path = Path("/var/lib/miles/parametrage")
    # Nombre de nœuds qu'une évaluation de template peut parcourir
    # (MILES_TRANSFORM_BUDGET). Même borne et même raison que dans le module de
    # paramétrage : le langage n'a pas de boucle, mais `$source` itère sur les données, et
    # la borne interrompt un template lancé sur un document démesuré. Elle compte DOUBLE
    # ici — c'est un tiers qui fournit le document, pas un auteur de template.
    transform_budget: int = Field(default=100_000, gt=0)
    # Où les documents déposés en mode gros fichier sont conservés (story 0f14adbd). AVEC
    # UN DÉFAUT, comme l'arbre servi, et pour la même raison : un volume non déclaré ne
    # doit pas empêcher de démarrer l'appariement et l'identité, qui n'ont que faire des
    # imports. Volume non monté : les fichiers partent au redéploiement, et ce que ça coûte
    # est la fenêtre de rejeu, pas l'état.
    ingestion_files_dir: Path = Path("/var/lib/miles/ingestion")
    # Taille maximale d'un dépôt (critère 19). Paramétrable parce que c'est une décision
    # d'exploitation : elle dépend du disque de la stack, pas du code.
    ingestion_file_max_bytes: int = Field(default=2 * 1024**3, gt=0)
    # Quota du répertoire des dépôts (critères 17 et 18), PARTAGÉ par tous les storages de
    # l'environnement : le disque est celui de la stack, et un storage volumineux ne doit
    # pas affamer les autres.
    ingestion_files_quota_bytes: int = Field(default=20 * 1024**3, gt=0)
    # Combien de jours un document déposé est conservé (critère 15). ZÉRO EST VALIDE
    # (critère 20) : le fichier est alors supprimé dès la fin de l'import, et aucun rejeu
    # n'est possible sans nouvel export du partenaire. C'est cette durée qui borne la
    # fenêtre de rejeu après un changement de template.
    ingestion_files_retention_days: int = Field(default=7, ge=0)
    # Plafond de DURÉE de la transaction d'écriture d'un import (critère 13). Son
    # dépassement termine l'import en échec plutôt que de laisser la transaction ouverte —
    # une transaction qui dure empêche autovacuum de nettoyer la table que l'import
    # malmène, et c'est précisément ce que l'aire de préparation évite.
    ingestion_apply_seconds: float = Field(default=60.0, gt=0)
    # Nombre de nœuds que les métadonnées d'un document peuvent porter. Elles sont un
    # EN-TÊTE : un document dont tout le volume est hors du tableau d'items n'est pas le
    # cas d'usage, et le dépassement est refusé plutôt que tronqué en silence.
    ingestion_metadata_budget: int = Field(default=10_000, gt=0)
