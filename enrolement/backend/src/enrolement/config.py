from __future__ import annotations

from pathlib import Path

from miles_socle.settings import SocleDatabaseSettings, SocleWebSettings

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


class DatabaseSettings(SocleDatabaseSettings):
    """Ce qu'il faut pour joindre la base et la migrer, plus le répertoire des migrations.

    Le socle ne porte **aucun SQL** (décision du 27/10/2026) : il n'a donc rien à dire de
    l'endroit où ce produit range ses migrations, et ce champ reste ici avec son défaut.
    Tout le reste — préfixe `MILES_`, `extra="forbid"`, accès base, niveau de journal —
    vient du socle, où il est écrit une fois pour les trois produits.
    """

    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR


class Settings(SocleWebSettings, DatabaseSettings):
    """Configuration du service web : la base, plus l'authentification.

    Ce produit n'ajoute **aucun champ propre** : sa configuration est celle du socle. La
    classe existe quand même, parce que c'est elle que `create_app` lit et que le jour où
    le métier de ce produit aura besoin d'un réglage, il s'ajoutera ici — pas au socle.
    """
