"""Le contrat d'ingestion, servi À TOUS.

**Routeur à part, et ouvert à tous (Gael, 05/11/2026).** Un contrat d'interface n'est
utile que si l'intégrateur peut l'ouvrir : le pointer par une URL, le télécharger, le
donner à un générateur de client. Derrière le portillon de sessions, il fallait un compte
sur le back-office de l'environnement pour lire ce qu'on demande à un tiers d'appeler.

**Ce que cela expose, et c'est délibéré** : les adresses des sources servies, leur mode
d'appel, et le schéma du modèle d'entrée de chacune. Rien d'autre — ni clé, ni objet, ni
nom de table, ni paramétrage au-delà de ce qu'une source promet. Ces adresses sont de
toute façon connues de l'intégrateur à qui on les donne, et elles restent fermées sans
clé d'API : publier le contrat n'ouvre aucune porte, il décrit celles qui existent.

Un routeur SÉPARÉ, parce que c'est de lui qu'`app.py` dérive la liste des routes
ouvertes : une route ouverte à côté de sa déclaration serait ouverte sans que personne
l'ait voulu, et l'inverse — déclarée sans exister — ne protégerait rien.
"""

from __future__ import annotations

from functools import cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from environnement.ingestion.api_ingest_file import INGEST_OPERATIONS
from environnement.ingestion.methods import IngestionMethods
from environnement.ingestion.source_contract import source_spec

router = APIRouter(prefix="/api/ingestion")


def methods_service(request: Request) -> IngestionMethods:
    service: IngestionMethods = request.app.state.ingestion_methods
    return service


Methods = Annotated[IngestionMethods, Depends(methods_service)]


@cache
def published() -> dict[str, Any]:
    """Le contrat versionné, engendré par la MÊME fonction que le fichier publié.

    Importé à l'appel et MÉMORISÉ : `published_contracts` construit une application pour
    en tirer la spec, et l'importer au chargement du module ferait tourner ce montage au
    démarrage. Le contrat ne dépend que du CODE, jamais de la version servie — c'est la
    spécialisation par source, elle, qui relit le paramétrage à chaque appel.
    """
    from environnement.published_contracts import openapi_contract

    return openapi_contract()


@router.get("/contract")
async def contract() -> dict[str, Any]:
    """Le contrat publié du point d'entrée, celui-là même qui est versionné.

    Des GABARITS d'adresse (`/ingest/{source}/{mode}`) : il vaut pour tout environnement,
    quel que soit son paramétrage. Celui d'une source est ci-dessous.
    """
    return published()


@router.get("/contract/{source}")
async def source_contract(source: str, service: Methods) -> dict[str, Any]:
    """Le contrat de CETTE source, adresses réelles et modèle d'entrée compris."""
    lues = await service.resolve_methods(operations=INGEST_OPERATIONS)
    spec = source_spec(published(), lues, source)
    if spec is None:
        # Une source que la version servie ne déclare pas. 404 et non un document vide :
        # un contrat sans chemin se lirait comme « cette source n'expose rien », ce qui
        # est faux — elle n'existe pas.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="source_inconnue")
    return spec
