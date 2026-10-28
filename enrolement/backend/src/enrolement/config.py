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
    """Configuration du service web : la base, l'authentification, et l'appariement.

    Tout vient du socle sauf la durée de vie d'une demande d'appariement, qui n'a de sens
    que pour ce produit : lui seul tient des demandes en attente.
    """

    # Au-delà, une demande jamais traitée expire et son secret est détruit (ticket
    # 6a0daab6). Une heure par défaut : assez pour aller chercher la personne qui doit
    # accepter, trop peu pour qu'un code reste valide sur un écran que plus personne ne
    # regarde. Bornée : zéro ferait expirer la demande avant que l'humain la voie, et une
    # valeur immense reviendrait à n'avoir pas d'expiration du tout.
    pairing_request_ttl_s: int = Field(default=3600, ge=60, le=7 * 24 * 3600)
