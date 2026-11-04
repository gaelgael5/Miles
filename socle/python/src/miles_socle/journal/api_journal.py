"""La route d'entretien des journaux, appelée par un déclencheur EXTÉRIEUR.

Décision de Gael du 3 novembre 2026, entre quatre pistes : le déclencheur périodique vient
de l'hôte et appelle cette route. Les trois autres ont été écartées — l'entretien au
démarrage ne purge plus quand une stack tourne longtemps, une boucle de fond rouvre la
question du multi-instance (enabler `e0919be6`, non fait), et `pg_cron` ferait sortir
l'entretien du code du produit et de ses suites de test.

**Authentifiée par un secret de STACK, pas par une session** : la garde est au socle
(`auth/stack_token.py`) depuis le 04/11/2026, deuxième usage — le module d'environnement a
sa propre route d'entretien, pour les imports de fichier. Fail closed deux fois : secret non
configuré, tout est refusé ; secret présenté différent, refusé.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from miles_socle.auth.stack_token import challenge_for, resolve_stack_token
from miles_socle.journal.maintenance import JournalMaintenance, MaintenanceReport

log = structlog.get_logger(__name__)

router = APIRouter()

MAINTENANCE_PATH = "/api/journal/maintenance"
REALM = "miles-journal"
# Le défi renvoyé avec un 401. Dérivé du royaume et non retapé : il ENTRE dans le contrat
# publié, et deux littéraux de même valeur auraient divergé au premier renommage.
CHALLENGE = challenge_for(REALM)


class TableOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    created: list[str]
    dropped: list[str]
    remaining: int


class MaintenanceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: str
    retention_days: int | None
    changed: bool
    tables: list[TableOut]


# `summary` et `description` ne sont pas décoratifs : ils sont ce que le contrat PUBLIÉ
# porte (`docs/contracts/miles-journal-maintenance.openapi.json`). Sans eux, le cadre
# dérive un titre du nom de la fonction — « Post Maintenance » — et le lecteur du contrat
# n'apprend rien de l'ordre des deux gestes, qui est précisément ce qui s'engage.
@router.post(
    MAINTENANCE_PATH,
    response_model=MaintenanceOut,
    summary="Entretenir le journal partitionné : poser l'avance, retirer ce qui a expiré",
    description=(
        "Pose les partitions manquantes du jour et des jours d'avance, PUIS retire celles"
        " qui ont dépassé la rétention. Les deux tables d'un même jour tombent dans la même"
        " transaction. Tout le SQL est idempotent : `changed` dit si la base a bougé, le"
        " code HTTP ne le dit pas."
    ),
)
async def post_maintenance(request: Request) -> MaintenanceOut:
    attendu: str | None = getattr(request.app.state, "journal_maintenance_token", None)
    resolve_stack_token(request, attendu, realm=REALM, event="journal_entretien_refuse")
    maintenance: JournalMaintenance = request.app.state.journal_maintenance
    return _out(await maintenance.resolve_maintain())


def _out(rapport: MaintenanceReport) -> MaintenanceOut:
    return MaintenanceOut(
        day=rapport.day.isoformat(),
        retention_days=rapport.retention_days,
        changed=rapport.changed,
        tables=[
            TableOut(
                table=t.table,
                created=[j.isoformat() for j in t.created],
                dropped=[j.isoformat() for j in t.dropped],
                remaining=t.remaining,
            )
            for t in rapport.tables
        ],
    )
