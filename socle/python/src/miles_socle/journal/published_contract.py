"""Le contrat publié de la route d'entretien des journaux partitionnés.

**Pourquoi au socle et non chez un produit.** La route est servie à l'identique par les
trois produits, parce que les trois portent la table `events`. Publiée depuis l'un d'eux,
elle aurait été publiée trois fois — trois fichiers qui divergent au premier changement
fait d'un seul côté, exactement ce que la mise en commun des chemins signés évitait déjà.

**Pourquoi elle a un contrat publié alors que `/api/events` n'en a pas.** Son appelant
n'est pas dans ce dépôt : c'est une unité systemd posée sur la machine par `dev-deploy.sh`.
`/api/events`, lui, est la surface d'un écran, et un écran change avec son back dans le
même commit — le test du module d'environnement le dit déjà de sa propre surface.

L'application montée ici ne porte QUE ce routeur : la spec d'un chemin et de ses formes de
réponse ne dépend d'aucun produit, et passer par le `build_app` de l'un d'eux ferait
dépendre le socle de ce produit — ce que la frontière refuse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI

from miles_socle.contracts import dump, file_write_contracts, published_spec
from miles_socle.journal.api_journal import CHALLENGE, MAINTENANCE_PATH
from miles_socle.journal.api_journal import router as journal_router
from miles_socle.journal.partitions import DAYS_AHEAD

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "docs" / "contracts"
OPENAPI_FILE = "miles-journal-maintenance.openapi.json"
PUBLISHED_PREFIXES = (MAINTENANCE_PATH,)

DESCRIPTION = (
    "Route d'entretien des journaux partitionnés, appelée par un déclencheur PÉRIODIQUE"
    " DE L'HÔTE — une unité systemd posée par le script de déploiement du produit, pas"
    " un humain et pas un système tiers.\n\n"
    "Servie à l'identique par les trois produits Miles — portail, module d'enrôlement,"
    " module d'environnement — parce que les trois portent la table `events`.\n\n"
    f"Un passage fait deux choses, dans cet ordre : il pose les partitions manquantes du"
    f" jour et des {DAYS_AHEAD} jours suivants, puis retire celles qui ont dépassé"
    " `MILES_JOURNAL_RETENTION_DAYS`. Poser d'abord garantit qu'un entretien interrompu"
    " laisse l'écriture possible. Les deux tables du journal d'un même jour tombent dans"
    " la MÊME transaction : c'est l'atomicité qui tient l'invariant « aucun lien ne"
    " survit à l'event qu'il désigne », la clé étrangère ayant dû être retirée pour que"
    " la purge soit possible.\n\n"
    "Tout le SQL de l'entretien est idempotent : le succès de l'appel ne dit donc rien de"
    " son effet, et c'est `changed` qui dit si la base a BOUGÉ.\n\n"
    "Authentification par un secret de STACK présenté en"
    " `Authorization: Bearer <MILES_JOURNAL_MAINTENANCE_TOKEN>` — un secret système, pas"
    " une session : rien d'humain n'est derrière. **Fail closed sans distinguer les"
    f" cas** : jeton absent, mal présenté, faux, ou route non configurée sur la stack"
    f" rendent tous `401` avec `{CHALLENGE}`. Dire « non configuré » renseignerait un"
    " appelant qui n'a rien à savoir.\n\n"
    "Si l'entretien ne tourne pas, rien ne tombe : l'écriture d'un event qui ne trouve"
    " pas sa partition la pose et réessaie une fois, sous point de sauvegarde. Un journal"
    " mal entretenu GROSSIT — ce qui se voit sur un disque et se répare — au lieu de"
    " faire tomber les écritures du produit.\n\n"
    "L'article docflow terminal-pr « Entretien des journaux partitionnés — route appelée"
    " par un déclencheur d'hôte » dit ce qui est garanti et ce qui casserait la"
    " compatibilité."
)


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(journal_router)
    return app


def openapi_contract() -> dict[str, Any]:
    spec = published_spec(
        _app().openapi(),
        info={
            "title": "Miles — entretien des journaux partitionnés",
            "version": "1",
            "description": DESCRIPTION,
        },
        prefixes=PUBLISHED_PREFIXES,
    )
    # Le refus n'est pas dans la spec engendrée : il est levé par le corps de la route, et
    # le cadre ne décrit que ce qu'une signature déclare. Un appelant qui ne le lit pas ici
    # le découvrirait en provoquant l'erreur — l'appel exploratoire qu'un contrat évite.
    spec["paths"][MAINTENANCE_PATH]["post"]["responses"]["401"] = {
        "description": (
            '`{"detail": "jeton_requis"}` — jeton absent, présenté sous un autre'
            " schéma que `Bearer`, faux, ou route non configurée sur cette stack. Les"
            f" quatre cas sont indiscernables, par choix. En-tête : `{CHALLENGE}`."
        )
    }
    spec["paths"][MAINTENANCE_PATH]["post"]["security"] = [{"journalMaintenanceToken": []}]
    spec["components"]["securitySchemes"] = {
        "journalMaintenanceToken": {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "Secret de stack `MILES_JOURNAL_MAINTENANCE_TOKEN`. Comparé par"
                " `hmac.compare_digest` : la comparaison d'un secret ne s'arrête pas au"
                " premier caractère qui diffère. Il ne passe jamais en argument de"
                " commande — le déclencheur le lit dans un fichier de configuration curl"
                " en 0600, qu'aucun `ps auxww` ni `systemctl cat` ne montre."
            ),
        }
    }
    return spec


def rendered() -> dict[str, str]:
    """Le contenu attendu de chaque fichier publié, à l'octet près."""
    return {OPENAPI_FILE: dump(openapi_contract())}


def main() -> None:
    file_write_contracts(CONTRACTS_DIR, rendered())
