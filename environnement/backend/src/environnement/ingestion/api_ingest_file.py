"""Le point d'entrée du mode gros fichier. Story `0f14adbd`.

**Un routeur et un chemin LITTÉRAL à part**, alors que les deux autres modes passent par
`/ingest/{source}/{mode}`. Trois raisons, et aucune n'est cosmétique :

- le corps n'est pas lu de la même façon — il est relayé tronçon par tronçon vers le
  disque, et jamais chargé en mémoire. La route des modes synchrones lit le corps entier
  avant d'appeler le service, et c'est ce qu'il ne faut pas faire ici ;
- la réponse n'est pas la même : **202**, un acquittement de prise en charge sans
  compte-rendu, parce que l'import se déroule ensuite ;
- le contrat publié y gagne : la méthode `fichier` montre son propre corps, ses propres
  refus et son propre code de succès, au lieu d'être une note en bas d'une description.

**Le chemin est DÉRIVÉ du gabarit commun** et non retapé : deux littéraux de même valeur
auraient divergé au premier renommage fait d'un seul côté, et l'essai depuis l'écran — qui
construit l'adresse depuis le gabarit — aurait frappé une route qui n'existe plus. Ce
routeur est inclus AVANT celui des modes synchrones : un chemin littéral doit l'emporter
sur un chemin à paramètre, sinon `fichier` tomberait sur le mode générique.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.apikeys.presentation import API_KEY_HEADER, key_from_headers
from starlette.requests import ClientDisconnect

from environnement.ingestion.api_ingest import (
    CHALLENGE,
    IDEMPOTENCY_HEADER,
    IDEMPOTENCY_PARAMETER,
    INGEST_PATH,
    SECURITY,
    AcknowledgementOut,
    RefusalOut,
    status_of,
)
from environnement.ingestion.deposit_files import FileDeposits
from environnement.ingestion.deposits import NotAuthenticated
from environnement.ingestion.files import FileRefused
from environnement.ingestion.imports import ImportLauncher
from environnement.ingestion.model import (
    BATCH,
    ELEMENT,
    FILE,
    MAX_BODY_BYTES,
    IngestionRefusal,
    declared_length,
)

INGEST_FILE_PATH = INGEST_PATH.format(source="{source}", mode=FILE)
# Sous quel gabarit chaque mode est monté. Ici parce que c'est le seul module qui connaît
# les DEUX, et dérivé de leurs constantes plutôt que retapé : deux littéraux de même
# valeur auraient divergé au premier renommage, et la page de service aurait cherché la
# signature d'une opération qui n'existe plus. Lu par la page de contrat et par l'aperçu
# de santé, qui doivent annoncer exactement les adresses que le dépôt accepte.
INGEST_OPERATIONS = {ELEMENT: INGEST_PATH, BATCH: INGEST_PATH, FILE: INGEST_FILE_PATH}

router = APIRouter(tags=["ingestion"])

# Combien d'octets on veut bien lire d'un corps qu'on a DÉJÀ refusé, pour que le refus
# arrive lisible à l'appelant. La raison du drainage est dans `_drain` ; la raison de la
# borne est qu'au-delà, absorber un document refusé donnerait à un appelant sans droits le
# pouvoir de nous faire lire deux gigaoctets. La valeur reprend `MAX_BODY_BYTES` : c'est
# déjà ce que ce module considère comme un corps qu'on lit sans y penser. DÉRIVÉE et
# non recopiée : deux littéraux de même valeur auraient divergé au premier relèvement
# fait d'un seul côté.
DRAIN_MAX = MAX_BODY_BYTES


def file_deposits(request: Request) -> FileDeposits:
    service: FileDeposits = request.app.state.ingestion_file_deposits
    return service


def import_launcher(request: Request) -> ImportLauncher:
    service: ImportLauncher = request.app.state.ingestion_imports
    return service


Deposits = Annotated[FileDeposits, Depends(file_deposits)]
Launcher = Annotated[ImportLauncher, Depends(import_launcher)]

_REFUSALS_DOC: dict[int | str, dict[str, object]] = {
    status.HTTP_200_OK: {
        "model": AcknowledgementOut,
        "description": (
            "Rejeu : la clé d'idempotence a retrouvé ce dépôt. Le document n'est pas"
            " reposé sur le disque, et aucun second import n'est mis en file."
        ),
    },
    status.HTTP_400_BAD_REQUEST: {
        "model": RefusalOut,
        "description": "`cle_idempotence_invalide` : la clé devient une clé d'unicité.",
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
        "description": "`source_inconnue` : l'adresse ne désigne rien.",
    },
    status.HTTP_409_CONFLICT: {
        "model": RefusalOut,
        "description": (
            "La version servie ne permet pas ce dépôt : `mode_non_declare` (l'entrée ne"
            " coche pas le mode fichier), `mode_ambigu`, `source_illisible`,"
            " `aucune_version_servie`, `cible_non_servie` — le storage, son modèle, la"
            " chaîne, ou un découpage qui ne se lit pas en flux ; `detail` dit lequel."
        ),
    },
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": RefusalOut,
        "description": (
            "`fichier_trop_grand` (la borne est dans `detail`) ou"
            " `quota_de_disque_atteint` (le disque de la stack est partagé par tous les"
            " storages de l'environnement). Les deux sont rendus AVANT la lecture du"
            " corps quand l'appelant annonce sa taille."
        ),
    },
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
        "model": RefusalOut,
        "description": (
            "`type_de_contenu_inattendu` : `application/json` ou"
            " `application/octet-stream`. Le contenu reste du JSON."
        ),
    },
}


# Le DOCUMENT attendu, déclaré en deux types de contenu : c'est la signature de cette
# méthode, et un intégrateur doit pouvoir la lire sans provoquer un refus pour l'apprendre.
# Le flux d'octets est admis en plus du JSON parce qu'un outil qui pousse un fichier
# n'annonce souvent rien de mieux ; le contenu, lui, reste du JSON.
_DOCUMENT_DOC: dict[str, object] = {
    "required": True,
    "description": (
        "Le document entier. Le jpath de découpage déclaré par l'entrée de source désigne"
        " le TABLEAU de ses items ; chaque item traverse la chaîne individuellement, et le"
        " document n'est jamais chargé entier en mémoire. Les clés placées hors de ce"
        " tableau — avant comme après — sont lues comme métadonnées du document."
    ),
    "content": {
        "application/json": {"schema": {"type": "object"}},
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    },
}


@router.post(
    INGEST_FILE_PATH,
    response_model=AcknowledgementOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_REFUSALS_DOC,
    openapi_extra={
        "security": SECURITY,
        "parameters": [IDEMPOTENCY_PARAMETER],
        "requestBody": _DOCUMENT_DOC,
    },
    summary="Déposer un DOCUMENT sur une entrée de source, en mode gros fichier",
    description=(
        "Le document est posé sur le disque de la stack, puis découpé et transformé item"
        " par item, hors de l'appel. La réponse n'est donc PAS un compte-rendu : c'est un"
        " acquittement de prise en charge, et `report` y est nul. L'issue de l'import se"
        " lit dans l'historique des ingestions, par l'identifiant rendu ici.\n\n"
        "Le document entier n'est jamais chargé en mémoire : les items sont émis un par un"
        " au jpath de découpage que l'entrée de source déclare, et chacun traverse la"
        " chaîne individuellement. Le document est CONSERVÉ un temps paramétrable, ce qui"
        " borne la fenêtre de rejeu après un changement de template."
    ),
)
async def deposit_file(
    source: str,
    request: Request,
    response: Response,
    service: Deposits,
    launcher: Launcher,
) -> object:
    """Prend en charge un document déposé sur l'entrée que cette adresse désigne."""
    # UN SEUL itérateur, tenu ici : il est donné au service, et c'est le MÊME qui est
    # drainé si le dépôt est refusé. Redemander `request.stream()` lèverait « Stream
    # consumed » sur un corps déjà lu en entier, et repartirait de la suite sur un corps
    # lu à moitié — deux comportements pour un seul geste.
    chunks = request.stream()
    try:
        accuse = await service.resolve_deposit(
            source=source,
            presented=key_from_headers(
                request.headers.get("authorization"), request.headers.get(API_KEY_HEADER)
            ),
            content_type=request.headers.get("content-type"),
            declared_length=declared_length(request.headers.get("content-length")),
            chunks=chunks,
            idempotency_key=request.headers.get(IDEMPOTENCY_HEADER),
        )
    except NotAuthenticated:
        # UN SEUL refus pour toutes les raisons : les distinguer offrirait un oracle.
        await _drain(chunks)
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": {"code": "authentification_requise", "detail": None}},
            headers={"WWW-Authenticate": CHALLENGE},
        )
    except FileRefused as refus:
        await _drain(chunks)
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": {"code": refus.code, "detail": refus.detail}},
        )
    except IngestionRefusal as refus:
        await _drain(chunks)
        return JSONResponse(
            status_code=status_of(refus.code),
            content={"detail": {"code": refus.code, "detail": refus.detail}},
        )
    # Le rejeu rend 200 et ne relance rien : l'import du premier dépôt a déjà eu lieu, ou
    # est encore en file. Relancer aurait fait rejouer un document pour rien.
    if accuse.replayed:
        response.status_code = status.HTTP_200_OK
    else:
        await launcher.resolve_launch(accuse)
    return AcknowledgementOut(
        id=accuse.id,
        source=accuse.source,
        mode=accuse.mode,
        object_count=accuse.object_count,
        received_at=accuse.received_at,
        state=accuse.state,
        replayed=accuse.replayed,
        report=None,
    )


async def _drain(chunks: AsyncIterator[bytes]) -> None:
    """Consomme ce qui reste du corps AVANT de rendre un refus, dans la limite de `DRAIN_MAX`.

    Sans ce geste, le gestionnaire répond et uvicorn referme la connexion alors que le
    mandataire écrit encore : nginx voit `writev() failed (104: Connection reset by peer)`,
    JETTE la réponse qu'il avait déjà reçue et rend un `502`. Le partenaire dont la clé est
    mauvaise lisait donc « bad gateway » au lieu de `authentification_requise` dès que son
    document dépassait les tampons de socket — c'est-à-dire toujours, en usage réel. Mesuré
    le 07/11/2026 sur un corps d'un mégaoctet, le backend ayant bien journalisé son 401
    (bug `abc1b595`).

    **Borné**, et c'est le point délicat : lire tout un document qu'on vient de refuser
    donnerait à un appelant sans droits le pouvoir de nous faire absorber deux gigaoctets.
    Au-delà de la borne on referme — l'appelant lit alors une connexion coupée, ce qui est
    le prix d'un envoi massif déjà refusé, et non le cas du partenaire qui se trompe de clé.

    Un client qui a déjà raccroché n'a rien à drainer : `ClientDisconnect` est donc une fin
    normale ici, et non une panne à faire remonter.
    """
    reste = DRAIN_MAX
    try:
        async for morceau in chunks:
            reste -= len(morceau)
            if reste < 0:
                return
    except ClientDisconnect:
        return
