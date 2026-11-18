from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from miles_socle.auth.author import request_author

from miles.datamodels.api_shapes import (
    ExampleOut,
    InferredOut,
    ListingOut,
    ModelContentOut,
    ModelCreate,
    ModelDeclare,
    ModelOut,
    ModelReplace,
    PathOut,
    PathsOut,
    SampleIn,
    listing_out,
    model_out,
)
from miles.datamodels.grammar import ModelSyntaxError
from miles.datamodels.inference import SampleNotAnObjectError, infer_root, read_sample
from miles.datamodels.refusals import REFUSALS as _REFUSALS
from miles.datamodels.refusals import error as _error
from miles.datamodels.refusals import refusal as _refusal
from miles.datamodels.service import DataModelsService

# Réservé à l'administrateur tant que les rôles n'existent pas : la passerelle refuse
# toute autre session. Le droit de lecture seule viendra avec les rôles (1b282b07).
router = APIRouter(prefix="/api/workspaces/{workspace_id}/data-models")


def data_models_service(request: Request) -> DataModelsService:
    service: DataModelsService = request.app.state.data_models
    return service


Service = Annotated[DataModelsService, Depends(data_models_service)]


@router.get("", response_model=ListingOut)
async def list_models(
    workspace_id: str, request: Request, service: Service, branch: str | None = None
) -> object:
    try:
        return listing_out(
            await service.resolve_list(request_author(request), workspace_id, branch=branch)
        )
    except _REFUSALS as exc:
        return _refusal(exc)


@router.get("/{scope}/{name}", response_model=ModelContentOut)
async def get_model(
    workspace_id: str,
    request: Request,
    scope: str,
    name: str,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, content = await service.resolve_get(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return ModelContentOut(**model_out(entry).model_dump(), content=content)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ModelOut)
async def create_model(
    workspace_id: str,
    body: ModelCreate,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, commit = await service.resolve_create(
            request_author(request),
            workspace_id,
            body.scope,
            body.name,
            body.content,
            branch=branch,
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        # Rejeu à l'identique : ni fichier ni commit de plus, et la réponse le dit.
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return model_out(entry)


@router.get("/{scope}/{name}/example", response_model=ExampleOut)
async def model_example(
    workspace_id: str,
    scope: str,
    name: str,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    """Le gabarit JSON du modèle : la forme à produire, pas une donnée réaliste."""
    try:
        example = await service.resolve_example(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return ExampleOut(example=example)


@router.get("/{scope}/{name}/paths", response_model=PathsOut)
async def model_paths(
    workspace_id: str,
    scope: str,
    name: str,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> object:
    """Les chemins du modèle ($.Account[0].Name), pour l'auto-complétion de l'éditeur."""
    try:
        found = await service.resolve_paths(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return PathsOut(
        paths=[
            PathOut(path=e.path, type=e.kind, description=e.description, format=e.format)
            for e in found
        ]
    )


@router.post("/inference", response_model=InferredOut, response_model_by_alias=True)
async def infer_from_sample(workspace_id: str, body: SampleIn, service: Service) -> object:
    """Déduit un schéma d'un échantillon, sans rien écrire ni toucher au dépôt.

    Transformation pure : le workspace n'est là que pour l'autorisation, le résultat
    n'est enregistré que si la personne le garde et enregistre le modèle.
    """
    try:
        sample = read_sample(body.sample, body.format)
    except ModelSyntaxError as exc:
        # Pas « yaml_invalide » : l'échantillon n'est pas le schéma, et il peut être du
        # JSON. Nommer la bonne chose évite de chercher l'erreur au mauvais endroit.
        detail = {"code": "echantillon_illisible", "message": exc.message}
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail | {"line": exc.line, "column": exc.column},
        )
    try:
        schema, unwrapped = infer_root(sample)
    except SampleNotAnObjectError as exc:
        # Refusé ICI plutôt que de rendre un schéma que la grammaire rejettera : un
        # modèle fabriqué pour être refusé fait chercher l'erreur dans le schéma.
        return _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "echantillon_sans_objet", "message": str(exc)},
        )
    return InferredOut(schema_body=schema, unwrapped=unwrapped)


@router.post("/declarations", status_code=status.HTTP_201_CREATED, response_model=ModelOut)
async def declare_model(
    workspace_id: str,
    body: ModelDeclare,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, commit = await service.resolve_declare(
            request_author(request), workspace_id, body.scope, body.label, body.slug, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        response.status_code = status.HTTP_200_OK
        response.headers["X-Miles-Already-Exists"] = "true"
    return model_out(entry)


@router.put("/{scope}/{name}", response_model=ModelOut)
async def replace_model(
    workspace_id: str,
    scope: str,
    name: str,
    body: ModelReplace,
    request: Request,
    response: Response,
    service: Service,
    branch: str | None = None,
) -> object:
    try:
        entry, commit = await service.resolve_replace(
            request_author(request), workspace_id, scope, name, body.content, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    if commit is None:
        # Même contenu : ni écriture ni commit, et la réponse le dit.
        response.headers["X-Miles-Already-Exists"] = "true"
    return model_out(entry)


@router.delete("/{scope}/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    workspace_id: str,
    scope: str,
    name: str,
    request: Request,
    service: Service,
    branch: str | None = None,
) -> Response:
    try:
        await service.resolve_delete(
            request_author(request), workspace_id, scope, name, branch=branch
        )
    except _REFUSALS as exc:
        return _refusal(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
