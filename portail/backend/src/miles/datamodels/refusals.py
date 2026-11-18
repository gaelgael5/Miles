"""Les refus des routes des modèles : une exception, un code, un statut.

Même forme que `contracts/refusals.py`, et pour la même raison : le code de refus est un
contrat d'interface, et il doit se lire d'un seul endroit. Dispersé dans les routes, il
finit par varier d'une route à l'autre pour la même cause.
"""

from __future__ import annotations

from fastapi import status
from fastapi.responses import JSONResponse

from miles.datamodels.errors import ModelInUseError, ModelNotFoundError
from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def error(code: int, detail: object) -> JSONResponse:
    return JSONResponse(status_code=code, content={"detail": detail})


REFUSALS = (
    ModelSyntaxError,
    ModelGrammarError,
    ModelNotFoundError,
    ModelInUseError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, ModelSyntaxError):
        detail = {"code": "yaml_invalide", "message": exc.message}
        return error(unprocessable, detail | {"line": exc.line, "column": exc.column})
    if isinstance(exc, ModelGrammarError):
        problems = [{"path": p.path, "code": p.code, "detail": p.detail} for p in exc.problems]
        return error(unprocessable, {"code": "modele_non_conforme", "problems": problems})
    if isinstance(exc, ModelInUseError):
        return error(status.HTTP_409_CONFLICT, {"code": "utilise", "by": exc.users})
    if isinstance(exc, ModelNotFoundError):
        return error(status.HTTP_404_NOT_FOUND, "modele_inconnu")
    if isinstance(exc, RepositoryUnavailableError):
        return error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        return error(unprocessable, {"field": exc.field})
    if isinstance(exc, WorkspaceConflictError):
        return error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    if isinstance(exc, WorkspaceNotFoundError):
        return error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc
