from __future__ import annotations

from fastapi import APIRouter, Path, Request, status
from fastapi.responses import JSONResponse
from miles_socle.signing.peers import IdentityError

from enrolement.pairing.api_schemas import (
    ConfidedConnectionDetailOut,
    ConfidedGitStateOut,
    confided_connection_out,
    confided_git_state_out,
)
from enrolement.pairing.confided_git_model import (
    ConfidedConnectionUnknownError,
    ConfidedGitInputError,
    NoParametragePairedError,
)
from enrolement.pairing.service import PairingService

# Ce que ce module DÉTIENT pour le compte du module de paramétrage (ticket edcf78bc).
#
# Un routeur à part, et non trois routes de plus dans `api_pairing.py` : celui-ci est à sa
# limite de 300 lignes, et la coupure suit une vraie frontière — là-bas on apparie et on
# révoque, ici on regarde ce qui a été confié. Routes d'ADMINISTRATION : le portillon exige
# une session, et aucune ne rend de credential.
router = APIRouter(prefix="/api/pairing/git-connections")


def _service(request: Request) -> PairingService:
    service: PairingService = request.app.state.pairing
    return service


def _error(exc: IdentityError) -> JSONResponse:
    if isinstance(exc, ConfidedGitInputError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": exc.field}
        )
    if isinstance(exc, NoParametragePairedError):
        # 409 et non 404 : la route existe et la personne y a droit, c'est l'état de
        # l'appariement qui l'empêche. Le détail NOMME la cause, parce que c'est le
        # critère 7 — « le dit plutôt que de laisser croire à une panne de la forge ».
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "aucun_module_de_parametrage"},
        )
    if isinstance(exc, ConfidedConnectionUnknownError):
        # 404 : cette connexion n'est pas confiée. Distinct du 409 ci-dessus, et la
        # différence est tout l'intérêt — « personne ne nous confie rien » et « celle-ci a
        # été supprimée à la source » n'appellent pas le même geste (critère 9).
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND, content={"detail": "connexion_inconnue"}
        )
    raise exc  # pragma: no cover - aucun autre refus ne sort de ces deux lectures


@router.get("", response_model=ConfidedGitStateOut)
async def get_confided_git_connections(request: Request) -> ConfidedGitStateOut:
    """Les connexions git confiées, leur révision et la date de la dernière transmission.

    Ne lève pas quand personne n'est apparié : elle rend un état dont le pair est nul.
    L'écran a besoin de la différence entre « aucun module de paramétrage » et « apparié,
    mais rien de confié » — la première attend un appariement, la seconde une transmission.
    """
    return confided_git_state_out(await _service(request).resolve_confided_git_state())


@router.get("/{connection_id}", response_model=ConfidedConnectionDetailOut)
async def get_confided_git_connection(
    request: Request,
    connection_id: str = Path(max_length=200),
) -> ConfidedConnectionDetailOut | JSONResponse:
    """Le détail d'une connexion confiée, et si son credential est lisible ici.

    La lecture OUVRE le chiffré pour savoir s'il s'ouvre, et l'oublie : la valeur ne
    traverse aucun champ de la réponse. C'est le seul diagnostic qu'on puisse faire du
    credential sans lire git — et lire git est le relais, reporté par Gael.
    """
    try:
        detail = await _service(request).resolve_confided_connection(connection_id)
    except IdentityError as exc:
        return _error(exc)
    return ConfidedConnectionDetailOut(
        connection=confided_connection_out(detail.connection),
        credential_readable=detail.credential_readable,
    )
