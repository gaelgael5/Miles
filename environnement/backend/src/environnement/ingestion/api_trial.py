"""La page de contrat du service d'ingestion : ce que chaque méthode attend, et l'essai.

Sous `/api`, donc derrière le portillon de sessions. **Une clé d'ingestion n'ouvre jamais
ces routes** : elle ne sait que déposer.

**Pourquoi le contrat se SERT ici plutôt que depuis `/openapi.json`.** La stack ne sert
volontairement ni `/docs` ni `/openapi.json` — ce seraient des routes hors du portillon, et
`app.py` porte cette décision. L'écran a quand même besoin de la forme publiée ; elle passe
donc par une route gardée, et c'est la MÊME fonction qui engendre le fichier versionné.
Deux sources auraient divergé, et l'écran aurait montré une forme que personne ne sert.
"""

from __future__ import annotations

from functools import cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict

from environnement.apikeys.self_key import SelfKeyRevokedError, SelfKeyService
from environnement.ingestion.api_ingest import INGEST_PATH
from environnement.ingestion.methods import IngestionMethods, Method
from environnement.ingestion.model import MAX_BODY_BYTES
from environnement.ingestion.trial import IngestionTrial

router = APIRouter(prefix="/api/ingestion")
# Refus propres à l'essai, distincts de ceux du point d'entrée : ils ne disent pas qu'un
# dépôt est fautif, ils disent que l'écran ne peut pas en lancer un.
REFUSAL_KEY_REVOKED = "cle_du_back_office_revoquee"
REFUSAL_BODY_TOO_LARGE = "corps_trop_grand"


def methods_service(request: Request) -> IngestionMethods:
    service: IngestionMethods = request.app.state.ingestion_methods
    return service


def trial_service(request: Request) -> IngestionTrial:
    service: IngestionTrial = request.app.state.ingestion_trial
    return service


def self_key_service(request: Request) -> SelfKeyService:
    service: SelfKeyService = request.app.state.ingestion_self_key
    return service


Methods = Annotated[IngestionMethods, Depends(methods_service)]
Trial = Annotated[IngestionTrial, Depends(trial_service)]
SelfKey = Annotated[SelfKeyService, Depends(self_key_service)]


class MethodOut(BaseModel):
    """Une méthode, telle que la page la présente."""

    model_config = ConfigDict(extra="forbid")
    source: str
    storage: str
    entry_model: str
    mode: str
    path: str
    # Faux pour un mode déclaré que la stack ne sert pas encore : la page le montre sans
    # bouton, plutôt que de promettre un dépôt qui sera refusé.
    served: bool
    # Le schéma du modèle d'entrée, renvois résolus. Nul quand on n'a pas pu le lire, et
    # `model_refusal` dit alors ce qui manque — jamais un corps vide, qui se lirait comme
    # « cette méthode n'attend rien ».
    request_schema: Any | None
    model_refusal: str | None
    example: Any | None


class MethodsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    methods: list[MethodOut]


class TrialOut(BaseModel):
    """Ce que le point d'entrée a répondu, rendu tel quel.

    `status` est le statut du DÉPÔT, pas celui de cette route : un lot entièrement rejeté
    rend 422 au partenaire, et la page doit le montrer comme tel plutôt que comme une
    panne de l'écran. Cette route répond donc 200 en portant un 422.
    """

    model_config = ConfigDict(extra="forbid")
    status: int
    body: Any


class RefusalDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    detail: str | None


class RefusalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: RefusalDetail


@cache
def _published() -> dict[str, Any]:
    """La forme publiée, engendrée une fois.

    Mise en cache parce qu'elle est déterminée par le CODE, pas par l'état : elle ne peut
    pas changer sans un redéploiement. Et l'engendrer construit une application entière —
    le faire à chaque ouverture de la page serait payé pour un résultat identique.
    """
    # Import DIFFÉRÉ, et il ne peut pas l'être autrement : `published_contracts`
    # construit l'application, qui inclut ce routeur. En tête de fichier, l'import
    # bouclerait au chargement.
    from environnement.published_contracts import openapi_contract

    return openapi_contract()


def _method(methode: Method) -> MethodOut:
    return MethodOut(
        source=methode.source,
        storage=methode.storage,
        entry_model=methode.entry_model,
        mode=methode.mode,
        path=methode.path,
        served=methode.served,
        request_schema=methode.schema,
        model_refusal=methode.model_refusal,
        example=methode.example,
    )


@router.get("/contract")
async def contract() -> dict[str, Any]:
    """Le contrat publié du point d'entrée, celui-là même qui est versionné."""
    return _published()


@router.get("/methods", response_model=MethodsOut)
async def methods(service: Methods) -> object:
    lues = await service.resolve_methods(ingest_path=INGEST_PATH)
    return MethodsOut(methods=[_method(methode) for methode in lues])


@router.post("/self-key", status_code=status.HTTP_201_CREATED)
async def reissue_self_key(request: Request, service: SelfKey) -> Response:
    """Réémet la clé du back-office, après une révocation. **Geste explicite.**

    Rien n'est rendu de la clé : sa valeur reste au serveur, et même son préfixe n'a rien
    à apprendre à l'écran — c'est la page des clés qui l'affiche.
    """
    await service.resolve_reissue(request_author(request))
    return Response(status_code=status.HTTP_201_CREATED)


@router.post("/try/{source}/{mode}", response_model=TrialOut)
async def try_method(source: str, mode: str, request: Request, service: Trial) -> object:
    """Dépose le corps reçu sur l'entrée désignée, avec la clé du back-office.

    Le corps n'est NI validé NI corrigé ici : le point d'entrée a ses refus, avec leurs
    codes et leurs positions, et c'est précisément ce qu'on veut montrer. Le seul contrôle
    fait avant est la taille, parce qu'il est inutile de recopier un corps démesuré dans
    un appel interne pour le faire refuser à l'arrivée.

    **Le mode fichier passe par ici comme les autres** (critère 21 de la story 0f14adbd) :
    le corps est alors le document, et le relais est le même. La borne, en revanche, reste
    celle de la MÉMOIRE — l'essai lit le corps entier pour le recopier dans un appel
    interne, là où le vrai point d'entrée écrit son flux sur le disque sans le garder. Un
    essai depuis l'écran sert à voir ce qu'un partenaire recevra, pas à éprouver un
    gigaoctet : c'est ce que dit le refus, avec sa borne dedans.
    """
    corps = await request.body()
    if len(corps) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": {"code": REFUSAL_BODY_TOO_LARGE, "detail": str(MAX_BODY_BYTES)}},
        )
    try:
        rendu = await service.resolve_trial(
            request.app, request_author(request), source=source, mode=mode, body=corps
        )
    except SelfKeyRevokedError:
        # Dit, plutôt que relayé en refus d'authentification nu : sans cela on
        # chercherait la cause du côté du paramétrage ou des octrois.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": {"code": REFUSAL_KEY_REVOKED, "detail": None}},
        )
    return TrialOut(status=rendu.status, body=rendu.body)
