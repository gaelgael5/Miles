from __future__ import annotations

from fastapi import status
from fastapi.responses import JSONResponse

from miles.contracts.openapi import (
    SUPPORTED,
    ContractInvalidError,
    ContractSyntaxError,
    UnsupportedVersionError,
)
from miles.contracts.service import ContractNotFoundError, ContractTakenError
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
    ContractSyntaxError,
    ContractInvalidError,
    UnsupportedVersionError,
    ContractTakenError,
    ContractNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)


def refusal(exc: Exception) -> JSONResponse:
    unprocessable = status.HTTP_422_UNPROCESSABLE_CONTENT
    if isinstance(exc, ContractSyntaxError):
        detail = {"code": "openapi_illisible", "message": exc.message}
        return error(unprocessable, detail | {"line": exc.line, "column": exc.column})
    if isinstance(exc, ContractInvalidError):
        problems = [{"path": p.path, "message": p.message} for p in exc.problems]
        return error(unprocessable, {"code": "openapi_invalide", "problems": problems})
    if isinstance(exc, UnsupportedVersionError):
        unsupported: dict[str, object] = {"code": "version_non_prise_en_charge"}
        return error(
            unprocessable, unsupported | {"found": exc.found, "accepted": sorted(SUPPORTED)}
        )
    if isinstance(exc, ContractTakenError):
        return error(status.HTTP_409_CONFLICT, {"code": "slug_pris", "by": exc.occupant})
    if isinstance(exc, ContractNotFoundError):
        return error(status.HTTP_404_NOT_FOUND, "contrat_inconnu")
    if isinstance(exc, RepositoryUnavailableError):
        return error(unprocessable, {"code": "acces_depot", "reason": exc.reason})
    if isinstance(exc, WorkspaceInputError):
        invalid = {"field": exc.field} | ({"reason": exc.reason} if exc.reason else {})
        return error(unprocessable, invalid)
    if isinstance(exc, WorkspaceConflictError):
        return error(status.HTTP_409_CONFLICT, exc.code)
    if isinstance(exc, BranchNotFoundError):
        return error(status.HTTP_404_NOT_FOUND, "branche_inconnue")
    if isinstance(exc, WorkspaceNotFoundError):
        return error(status.HTTP_404_NOT_FOUND, "workspace_inconnu")
    raise exc
