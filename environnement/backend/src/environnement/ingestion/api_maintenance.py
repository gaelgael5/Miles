"""La route d'entretien des imports, appelée par un déclencheur d'HÔTE. Story `0f14adbd`.

**Le MÊME secret de stack que l'entretien des journaux**, et la même garde (au socle depuis
le 04/11/2026). C'est un choix : les deux routes servent le même déclencheur d'hôte, et deux
secrets à injecter pour une même tâche auraient fini par n'en avoir qu'un de configuré — la
seconde route serait restée inerte sans que rien ne le dise, et avec elle la purge.

**Ce que cette route tient** : les imports qu'un conteneur arrêté a laissés en cours
(critère 14), la purge des documents expirés (critère 16) et sous quota (critère 17), les
fichiers que plus aucune ligne ne réclame, et le rattrapage de la file.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from miles_socle.auth.stack_token import resolve_stack_token
from pydantic import BaseModel, ConfigDict

from environnement.ingestion.maintenance import ImportsMaintenance, ImportsMaintenanceReport

router = APIRouter()

IMPORTS_MAINTENANCE_PATH = "/api/ingestion/maintenance"
REALM = "miles-ingestion"


class ImportsMaintenanceOut(BaseModel):
    """Des COMPTES, et non un code de retour : « c'est passé » ne dit pas si ça a bougé."""

    model_config = ConfigDict(extra="forbid")

    requeued: int
    failed: int
    purged_expired: int
    purged_for_quota: int
    orphan_files_removed: int
    drained: int
    used_bytes: int
    changed: bool


def imports_maintenance(request: Request) -> ImportsMaintenance:
    service: ImportsMaintenance = request.app.state.ingestion_maintenance
    return service


Maintenance = Annotated[ImportsMaintenance, Depends(imports_maintenance)]


@router.post(
    IMPORTS_MAINTENANCE_PATH,
    response_model=ImportsMaintenanceOut,
    summary="Entretenir les imports : rattraper les interrompus, purger les documents",
    description=(
        "Remet en file les imports qu'un arrêt a laissés en cours, purge les documents"
        " déposés expirés puis — si le quota reste dépassé — les plus anciens encore"
        " conservés, ôte les fichiers que plus aucune ligne ne réclame, et draine la file"
        " en dernier. Un document dont l'import est en file ou en cours n'est JAMAIS"
        " purgé. L'historique d'une ingestion ne disparaît pas avec son document."
    ),
)
async def post_imports_maintenance(request: Request, service: Maintenance) -> ImportsMaintenanceOut:
    attendu: str | None = getattr(request.app.state, "journal_maintenance_token", None)
    resolve_stack_token(request, attendu, realm=REALM, event="imports_entretien_refuse")
    return _out(await service.resolve_maintain())


def _out(rapport: ImportsMaintenanceReport) -> ImportsMaintenanceOut:
    return ImportsMaintenanceOut(
        requeued=rapport.requeued,
        failed=rapport.failed,
        purged_expired=rapport.purged_expired,
        purged_for_quota=rapport.purged_for_quota,
        orphan_files_removed=rapport.orphan_files_removed,
        drained=rapport.drained,
        used_bytes=rapport.used_bytes,
        changed=rapport.changed,
    )
