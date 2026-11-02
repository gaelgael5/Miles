from __future__ import annotations

from pathlib import Path
from typing import Any

from miles_socle.contracts import dump, file_write_contracts, published_spec

from environnement.app import build_app
from environnement.ingestion.api_ingest import IDEMPOTENCY_HEADER
from environnement.ingestion.model import MAX_BODY_BYTES

# Contrat publié du module d'environnement : le point d'entrée d'ingestion, et lui seul.
#
# C'est la SEULE surface de ce produit qu'un système tiers appelle. Tout le reste —
# clés d'API, espaces de stockage, appariement — est la surface de son propre écran, et
# un écran n'est pas un contrat : il change avec lui, dans le même commit.
#
# Engendré depuis le code, versionné, et un test vérifie qu'il est à jour. Écrit à la
# main, il divergerait du service sans que rien ne le signale.
CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts"
OPENAPI_FILE = "miles-ingestion.openapi.json"
PUBLISHED_PREFIXES = ("/ingest/",)


def openapi_contract() -> dict[str, Any]:
    return published_spec(
        build_app().openapi(),
        info={
            "title": "Miles — ingestion de données dans un environnement",
            "version": "1",
            "description": (
                "Point d'entrée par lequel un système tiers DÉPOSE des objets JSON dans"
                " un environnement Miles. Réception, pas collecte : Miles n'appelle"
                " personne.\n\n"
                "L'adresse désigne une SOURCE du paramétrage servi et le MODE d'appel."
                " La source dit où les objets atterrissent, par quel modèle on les"
                " décrit et quelle chaîne les transforme ; le mode dit comment on"
                " dépose — `element` pour un objet, `tableau` pour un lot. Ce qu'une"
                " source expose est déclaré dans son paramétrage : un mode non coché"
                " est refusé, jamais accepté sans effet.\n\n"
                "Authentification par clé d'API propre à cet environnement, présentée en"
                " `Authorization: Bearer <clé>` ou en `X-API-Key`. Une clé n'ouvre que"
                " les sources qu'on lui a octroyées, et l'octroi est revérifié contre la"
                " version servie à chaque appel : une source retirée du paramétrage"
                " ferme le point d'entrée.\n\n"
                f"`{IDEMPOTENCY_HEADER}` rend un rejeu sûr : la même valeur réémise rend"
                " le MÊME accusé, en 200 au lieu de 201, sans rien enregistrer deux fois."
                " Sans cet en-tête, deux dépôts identiques sont deux ingestions — c'est"
                " l'écriture qui déduplique, par empreinte, pas la réception.\n\n"
                "L'accusé dit que le lot est REÇU et conservé tel quel, pas qu'il est"
                f" écrit. Corps en `application/json`, {MAX_BODY_BYTES} octets au plus."
                " L'article docflow terminal-pr « Contrats d'interface » dit ce qui est"
                " garanti et ce qui ne l'est pas."
            ),
        },
        prefixes=PUBLISHED_PREFIXES,
    )


def rendered() -> dict[str, str]:
    """Le contenu attendu de chaque fichier publié, à l'octet près."""
    return {OPENAPI_FILE: dump(openapi_contract())}


def main() -> None:
    file_write_contracts(CONTRACTS_DIR, rendered())
