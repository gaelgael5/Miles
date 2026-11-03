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
