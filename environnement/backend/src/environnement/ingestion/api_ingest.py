"""Le point d'entrée d'ingestion : la seule surface de ce module ouverte à un TIERS.

**Hors de `/api`, et c'est délibéré.** La passerelle d'authentification ne garde que
`/api`, et elle garde des SESSIONS — un cookie, un humain derrière. Ce point d'entrée
n'en a aucun : il est appelé de machine à machine et s'authentifie par clé d'API. Le
ranger sous `/api` aurait obligé à l'inscrire dans une liste blanche de chemins exacts,
alors qu'il porte des paramètres de chemin ; et surtout, la surface MCP du portail a
déjà tranché cette question dans le même sens (story 3429986c).

**La contrepartie est entière ici** : cette route refuse elle-même tout appel qui ne
présente pas une clé active octroyée sur la source visée, AVANT de lire quoi que ce soit
du corps ou de la version servie. Un test l'affirme, et un autre affirme qu'aucune autre
route de ce module ne vit hors de la passerelle.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.apikeys.presentation import API_KEY_HEADER, key_from_headers
from pydantic import BaseModel, ConfigDict

from environnement.ingestion.model import (
    REFUSAL_AUCUNE_VERSION,
    REFUSAL_CIBLE_NON_SERVIE,
    REFUSAL_CORPS_TROP_GRAND,
    REFUSAL_LOT_TROP_GRAND,
    REFUSAL_MODE_AMBIGU,
    REFUSAL_MODE_INCONNU,
    REFUSAL_MODE_NON_DECLARE,
    REFUSAL_MODE_NON_SERVI,
    REFUSAL_SOURCE_ILLISIBLE,
    REFUSAL_SOURCE_INCONNUE,
    REFUSAL_TYPE_DE_CONTENU,
    Acknowledgement,
    IngestionRefusal,
)
from environnement.ingestion.service import IngestionService, NotAuthenticated

INGEST_PATH = "/ingest/{source}/{mode}"
# En-tête d'idempotence, au nom conventionnel : un appelant qui rejoue une remise dont
# l'acquittement s'est perdu obtient le même accusé, et rien n'est persisté deux fois.
IDEMPOTENCY_HEADER = "Idempotency-Key"
# Le défi renvoyé avec un 401 : il dit à l'appelant COMMENT présenter sa clé.
CHALLENGE = 'Bearer realm="miles-ingest"'

router = APIRouter(tags=["ingestion"])

# Le code HTTP de chaque refus. Écrit en table et non deviné à l'écriture : c'est une
# partie du CONTRAT, donc elle doit se lire d'un bloc — et un refus ajouté sans son code
# se verrait ici, plutôt que de partir en 500.
_STATUS = {
    REFUSAL_MODE_INCONNU: status.HTTP_404_NOT_FOUND,
    REFUSAL_SOURCE_INCONNUE: status.HTTP_404_NOT_FOUND,
    REFUSAL_SOURCE_ILLISIBLE: status.HTTP_409_CONFLICT,
    REFUSAL_MODE_NON_DECLARE: status.HTTP_409_CONFLICT,
    REFUSAL_MODE_AMBIGU: status.HTTP_409_CONFLICT,
    REFUSAL_MODE_NON_SERVI: status.HTTP_409_CONFLICT,
    REFUSAL_AUCUNE_VERSION: status.HTTP_409_CONFLICT,
    REFUSAL_CIBLE_NON_SERVIE: status.HTTP_409_CONFLICT,
    REFUSAL_TYPE_DE_CONTENU: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    REFUSAL_LOT_TROP_GRAND: status.HTTP_413_CONTENT_TOO_LARGE,
    REFUSAL_CORPS_TROP_GRAND: status.HTTP_413_CONTENT_TOO_LARGE,
}


def ingestion_service(request: Request) -> IngestionService:
    service: IngestionService = request.app.state.ingestion
    return service


Service = Annotated[IngestionService, Depends(ingestion_service)]


class ObjectOutcomeOut(BaseModel):
    """Le sort d'UN objet du lot. `position` est son rang, 0 pour le premier.

    Le rang est là pour les objets dont la clé n'a pas pu être extraite : c'est alors la
    seule prise de l'appelant pour retrouver lequel de ses objets est en cause.
    """

    model_config = ConfigDict(extra="forbid")
    position: int
    # « ecrit » (créé ou corps réécrit), « inchange » (même empreinte : seul `vu_le` a
    # avancé), « rejete » (rien n'a été écrit pour cet objet).
    outcome: str
    key: str | None
    reason: str | None
    detail: str | None


class ReportOut(BaseModel):
    """Le compte-rendu du lot : les comptes, le sort de chaque objet, les anomalies.

    `unchanged` est distinct de `written`, et c'est tout l'objet de l'écriture
    différentielle : un réimport à l'identique ne réécrit aucun corps et ne touche aucune
    date de modification — il n'avance que la date de dernière vue.
    """

    model_config = ConfigDict(extra="forbid")
    received: int
    written: int
    unchanged: int
    rejected: int
    objects: list[ObjectOutcomeOut]
    # Signalées et non corrigées : deux objets de même clé dans un même lot, par exemple.
    # Le dernier valide gagne, et l'appelant doit savoir que sa source se contredit.
    anomalies: list[str]


class AcknowledgementOut(BaseModel):
    """L'accusé : ce qui est reçu, et ce que le traitement en a fait."""

    model_config = ConfigDict(extra="forbid")
    id: str
    source: str
    mode: str
    object_count: int
    received_at: datetime
    state: str
    # Vrai quand la clé d'idempotence a retrouvé un dépôt déjà pris : l'accusé est le
    # même qu'à la première remise, et rien n'a été persisté une seconde fois.
    replayed: bool
    # Nul seulement si le lot n'a pas été traité — ce qui n'arrive pas sur les modes
    # servis ici, qui traitent dans l'appel. Le champ reste facultatif parce que le mode
    # `fichier` n'accusera que la prise en charge (story 0f14adbd).
    report: ReportOut | None


class RefusalDetail(BaseModel):
    """La raison d'un refus. `code` est STABLE : c'est sur lui qu'un appelant se branche."""

    model_config = ConfigDict(extra="forbid")
    code: str
    # Ce qui permet de corriger sans appel exploratoire : le mode fautif, le plafond
    # dépassé, la position de l'erreur de syntaxe. Nul quand le code suffit.
    detail: str | None


class RefusalOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: RefusalDetail


# Les refus ENTRENT dans le contrat publié. Sans cette déclaration, la spec engendrée ne
# montrerait que le succès et le 422 du cadre, et un appelant devrait découvrir les codes
# en provoquant les erreurs — exactement l'appel exploratoire qu'un contrat évite.
_REFUSALS_DOC: dict[int | str, dict[str, object]] = {
    status.HTTP_200_OK: {
        "model": AcknowledgementOut,
        "description": "Rejeu : la clé d'idempotence a retrouvé ce dépôt. Rien n'est créé.",
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": RefusalOut,
        "description": (
            "Corps vide (`corps_vide`), JSON invalide avec sa position (`json_invalide`),"
            " forme attendue non respectée (`objet_attendu`, `tableau_attendu`), clé"
            " d'idempotence mal formée (`cle_idempotence_invalide`)."
        ),
    },
    status.HTTP_401_UNAUTHORIZED: {
        "model": RefusalOut,
        "description": (
            "`authentification_requise`. UN SEUL code pour toutes les raisons — clé"
            " absente, mal formée, inconnue, révoquée, sans octroi sur cette source, ou"
            " source retirée de la version servie. Les distinguer offrirait un oracle."
        ),
    },
    status.HTTP_404_NOT_FOUND: {
        "model": RefusalOut,
        "description": "`mode_inconnu`, `source_inconnue` : l'adresse ne désigne rien.",
    },
    status.HTTP_409_CONFLICT: {
        "model": RefusalOut,
        "description": (
            "La version servie ne permet pas ce dépôt : `mode_non_declare` (l'entrée ne"
            " coche pas ce mode), `mode_ambigu` (deux entrées l'exposent), `mode_non_servi`"
            " (déclaré, pas encore branché), `source_illisible`, `aucune_version_servie`,"
            " `cible_non_servie` (le storage, son modèle ou la chaîne manquent de la"
            " version servie — `detail` dit lequel)."
        ),
    },
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": RefusalOut,
        "description": (
            "`lot_trop_grand` (plus d'objets que le plafond du mode tableau, qui est dit"
            " dans `detail`) ou `corps_trop_grand` (taille en octets)."
        ),
    },
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
        "model": RefusalOut,
        "description": "`type_de_contenu_inattendu` : seul `application/json` est reçu.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": AcknowledgementOut,
        "description": (
            "**Le lot est reçu et persisté, mais TOUS ses objets ont été rejetés** :"
            " aucune ligne n'a été écrite, et aucune date de dernière vue n'a avancé."
            " Le corps est l'accusé complet, `state` vaut `rejete`, et `report.objects`"
            " dit pour chaque objet pourquoi — `cle_non_extractible`,"
            " `transformation_en_echec`, `modele_non_respecte`,"
            " `objet_d_origine_manuelle`. Un lot dont UN SEUL objet aboutit rend 201."
        ),
    },
}


def _report_out(accuse: Acknowledgement) -> ReportOut | None:
    rapport = accuse.report
    if rapport is None:
        return None
    return ReportOut(
        received=rapport.received,
        written=rapport.written,
        unchanged=rapport.unchanged,
        rejected=rapport.rejected,
        objects=[ObjectOutcomeOut(**o.as_json()) for o in rapport.objects],
        anomalies=list(rapport.anomalies),
    )


def _out(accuse: Acknowledgement) -> AcknowledgementOut:
    return AcknowledgementOut(
        id=accuse.id,
        source=accuse.source,
        mode=accuse.mode,
        object_count=accuse.object_count,
        received_at=accuse.received_at,
        state=accuse.state,
        replayed=accuse.replayed,
        report=_report_out(accuse),
    )


@router.post(
    INGEST_PATH,
    response_model=AcknowledgementOut,
    status_code=status.HTTP_201_CREATED,
    responses=_REFUSALS_DOC,
    summary="Déposer un lot d'objets sur une entrée de source",
)
async def deposit(
    source: str, mode: str, request: Request, response: Response, service: Service
) -> object:
    """Dépose un lot d'objets JSON sur l'entrée que cette adresse désigne."""
    corps = await request.body()
    try:
        accuse = await service.resolve_deposit(
            source=source,
            mode=mode,
            presented=key_from_headers(
                request.headers.get("authorization"), request.headers.get(API_KEY_HEADER)
            ),
            content_type=request.headers.get("content-type"),
            body=corps,
            idempotency_key=request.headers.get(IDEMPOTENCY_HEADER),
        )
    except NotAuthenticated:
        # UN SEUL refus pour toutes les raisons — clé absente, mal formée, inconnue,
        # révoquée, sans octroi, ou source retirée de la version servie. Les distinguer
        # offrirait un oracle : on apprendrait qu'une clé existe, ou qu'une source est
        # déclarée, sans en détenir aucune.
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": {"code": "authentification_requise", "detail": None}},
            headers={"WWW-Authenticate": CHALLENGE},
        )
    except IngestionRefusal as refus:
        return JSONResponse(
            status_code=_STATUS.get(refus.code, status.HTTP_400_BAD_REQUEST),
            content={"detail": {"code": refus.code, "detail": refus.detail}},
        )
    # Trois codes, et chacun dit quelque chose que le corps ne dirait qu'après lecture :
    # 200 un rejeu (rien de créé), 422 un lot dont RIEN n'a abouti, 201 le cas où au moins
    # un objet a été traité. Un appelant doit pouvoir se brancher sur le code.
    if accuse.report is not None and accuse.report.all_rejected:
        response.status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        response.status_code = status.HTTP_200_OK if accuse.replayed else status.HTTP_201_CREATED
    return _out(accuse)
