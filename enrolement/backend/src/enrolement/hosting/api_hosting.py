"""Les routes d'ADMINISTRATION de la version hébergée : lire les versions, en ordonner une.

Routes d'administration : le portillon exige une session, et aucune ne rend de credential
ni de contenu de dépôt. Le relais, lui, est authentifié par SIGNATURE et vit ailleurs.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from miles_socle.auth.author import request_author
from pydantic import BaseModel, ConfigDict, Field

from enrolement.environments.model import EnvironmentNotFoundError
from enrolement.hosting.model import (
    HostedVersion,
    HostingError,
    HostingInputError,
    NoRepositoryError,
    NoWorkspaceHostedError,
    RepositoryUnreadableError,
    VersionUnknownError,
    WorkspaceNotConfidedError,
)
from enrolement.hosting.service import HostingService

router = APIRouter(prefix="/api/environments/{environment_id}")


def _service(request: Request) -> HostingService:
    service: HostingService = request.app.state.hosting
    return service


class VersionOut(BaseModel):
    """Une version publiée du workspace, telle que le dépôt la porte."""

    model_config = ConfigDict(extra="forbid")

    number: int
    label: str
    commit: str
    author: str
    saved_at: str
    # Nulle pour une étiquette d'avant les branches filles : l'affichage le dit plutôt
    # que d'inventer une branche.
    branch: str | None


class HostedVersionOut(BaseModel):
    """Ce qui est ordonné, et l'INSTANTANÉ de ce que le pair a répondu.

    `acked_at` accompagne toujours `served_commit` et `refusal` : l'écran dit « au
    <instant> », jamais « actuellement ». Le pair peut avoir redémarré, fini d'appliquer
    ou perdu son disque depuis, et nous n'en savons rien tant qu'on ne lui a pas reparlé.
    """

    model_config = ConfigDict(extra="forbid")

    number: int
    commit: str
    ordered_at: str
    served_commit: str | None
    refusal: str | None
    acked_at: str | None
    # Calculé ici et pas dans l'écran : « à jour » est la comparaison du commit servi au
    # commit ordonné, et la refaire côté front la ferait un jour autrement.
    up_to_date: bool


class OrderIn(BaseModel):
    """Le NUMÉRO de la version choisie, et lui seul.

    Pas de commit : il est lu dans le dépôt par le serveur. L'accepter ici reviendrait à
    laisser désigner un contenu arbitraire du dépôt — et c'est ce commit qui autorise
    ensuite le relais à servir.
    """

    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)


def hosted_out(hebergee: HostedVersion) -> HostedVersionOut:
    return HostedVersionOut(
        number=hebergee.number,
        commit=hebergee.commit,
        ordered_at=hebergee.ordered_at.isoformat(),
        served_commit=hebergee.served_commit,
        refusal=hebergee.refusal,
        acked_at=None if hebergee.acked_at is None else hebergee.acked_at.isoformat(),
        up_to_date=hebergee.up_to_date,
    )


def _refusal(exc: Exception) -> JSONResponse:
    """Chaque refus a son code, parce que chacun appelle un geste différent.

    Un message unique ferait chercher au même endroit une absence de workspace, un
    paramétrage révoqué, un dépôt non configuré et des identifiants refusés par la forge.
    """
    if isinstance(exc, EnvironmentNotFoundError):
        return _json(status.HTTP_404_NOT_FOUND, "environnement_inconnu")
    if isinstance(exc, HostingInputError):
        return _json(status.HTTP_422_UNPROCESSABLE_CONTENT, exc.field)
    if isinstance(exc, NoWorkspaceHostedError):
        return _json(status.HTTP_409_CONFLICT, "aucun_workspace_place")
    if isinstance(exc, WorkspaceNotConfidedError):
        return _json(status.HTTP_409_CONFLICT, "workspace_non_confie")
    if isinstance(exc, NoRepositoryError):
        return _json(status.HTTP_409_CONFLICT, "depot_non_configure")
    if isinstance(exc, VersionUnknownError):
        return _json(status.HTTP_404_NOT_FOUND, "version_inconnue")
    if isinstance(exc, RepositoryUnreadableError):
        # La raison de git traverse : « identifiants », « dépôt inexistant » et
        # « injoignable » n'appellent pas le même geste.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": {"code": "depot_illisible", "reason": exc.reason}},
        )
    raise exc  # pragma: no cover - aucun autre refus ne sort de ce service


def _json(code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


@router.get("/versions", response_model=list[VersionOut])
async def list_versions(environment_id: UUID, request: Request) -> object:
    """Les versions publiées du workspace que cet environnement héberge.

    Lues dans git à chaque appel, avec le credential confié. Pas de cache applicatif : une
    liste servie d'un cache ferait choisir une version supprimée depuis, et le miroir git
    est déjà le cache — il ne récupère que ce qui a changé.
    """
    try:
        versions = await _service(request).resolve_versions(environment_id)
    except (HostingError, EnvironmentNotFoundError) as exc:
        return _refusal(exc)
    return [
        VersionOut(
            number=v.number,
            label=v.label,
            commit=v.commit,
            author=v.author,
            saved_at=v.saved_at.isoformat(),
            branch=v.branch,
        )
        for v in versions
    ]


@router.get("/version", response_model=HostedVersionOut)
async def get_ordered_version(environment_id: UUID, request: Request) -> object:
    """La version ordonnée à cet environnement, et l'instantané de sa dernière réponse.

    404 quand aucune ne l'est, et non un objet aux champs nuls : « aucune version n'a été
    choisie » est un état à part entière, et l'écran n'y propose pas le même geste qu'à
    une version ordonnée mais non appliquée.
    """
    hebergee = await _service(request).resolve_ordered_version(environment_id)
    if hebergee is None:
        return _json(status.HTTP_404_NOT_FOUND, "aucune_version_ordonnee")
    return hosted_out(hebergee)


@router.put("/version", response_model=HostedVersionOut)
async def order_version(environment_id: UUID, body: OrderIn, request: Request) -> object:
    """Associe une version à l'environnement, et lui pousse l'ordre de la servir.

    Rend 200 même quand le pair n'a pas appliqué : le choix est NOTRE état et il est
    enregistré. Ce que le pair en a fait se lit dans `served_commit` et `refusal`, et
    l'écran propose alors de renvoyer l'ordre. Rendre une erreur ferait croire que rien
    n'a été retenu, et l'humain rechoisirait la même version indéfiniment.
    """
    try:
        hebergee, _ = await _service(request).resolve_order_version(
            request_author(request), environment_id, body.number
        )
    except (HostingError, EnvironmentNotFoundError) as exc:
        return _refusal(exc)
    return hosted_out(hebergee)


@router.post("/version/resend", response_model=HostedVersionOut)
async def resend_order(environment_id: UUID, request: Request) -> object:
    """Repousse l'ordre déjà enregistré, sans le changer.

    Le geste de réparation : un environnement redémarré ou dont le volume est neuf ne sait
    pas qu'une version lui est ordonnée, et n'a aucun moyen de l'apprendre seul.
    """
    try:
        hebergee, _ = await _service(request).resolve_resend_order(
            request_author(request), environment_id
        )
    except (HostingError, EnvironmentNotFoundError) as exc:
        return _refusal(exc)
    return hosted_out(hebergee)
