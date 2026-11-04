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

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from miles_socle.apikeys.presentation import API_KEY_HEADER, key_from_headers

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
from environnement.ingestion.model import BATCH, ELEMENT, FILE, IngestionRefusal

INGEST_FILE_PATH = INGEST_PATH.format(source="{source}", mode=FILE)
# Sous quel gabarit chaque mode est monté. Ici parce que c'est le seul module qui connaît
# les DEUX, et dérivé de leurs constantes plutôt que retapé : deux littéraux de même
# valeur auraient divergé au premier renommage, et la page de service aurait cherché la
# signature d'une opération qui n'existe plus. Lu par la page de contrat et par l'aperçu
# de santé, qui doivent annoncer exactement les adresses que le dépôt accepte.
INGEST_OPERATIONS = {ELEMENT: INGEST_PATH, BATCH: INGEST_PATH, FILE: INGEST_FILE_PATH}

router = APIRouter(tags=["ingestion"])


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
    try:
        accuse = await service.resolve_deposit(
            source=source,
            presented=key_from_headers(
                request.headers.get("authorization"), request.headers.get(API_KEY_HEADER)
            ),
            content_type=request.headers.get("content-type"),
            declared_length=_declared(request.headers.get("content-length")),
            chunks=request.stream(),
            idempotency_key=request.headers.get(IDEMPOTENCY_HEADER),
        )
    except NotAuthenticated:
        # UN SEUL refus pour toutes les raisons : les distinguer offrirait un oracle.
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": {"code": "authentification_requise", "detail": None}},
            headers={"WWW-Authenticate": CHALLENGE},
        )
    except FileRefused as refus:
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": {"code": refus.code, "detail": refus.detail}},
        )
    except IngestionRefusal as refus:
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


def _declared(header: str | None) -> int | None:
    """La taille annoncée, si elle est annoncée et lisible.

    Une valeur illisible est traitée comme une absence plutôt que refusée : la garde en
    cours d'écriture reste, et refuser sur un en-tête mal formé aurait fermé la porte à un
    client correct derrière un relais bavard. Ce qui est refusé pour de bon, c'est le
    dépôt qui dépasse les bornes — mesuré, pas annoncé.
    """
    if header is None:
        return None
    try:
        return int(header)
    except ValueError:
        return None
