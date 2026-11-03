"""La route d'entretien des journaux, appelée par un déclencheur EXTÉRIEUR.

Décision de Gael du 3 novembre 2026, entre quatre pistes : le déclencheur périodique vient
de l'hôte et appelle cette route. Les trois autres ont été écartées — l'entretien au
démarrage ne purge plus quand une stack tourne longtemps, une boucle de fond rouvre la
question du multi-instance (enabler `e0919be6`, non fait), et `pg_cron` ferait sortir
l'entretien du code du produit et de ses suites de test.

**Authentifiée par un secret de STACK, pas par une session.** Rien d'humain n'est derrière :
le cookie de session est `Secure` et lié à une personne, et un déclencheur d'hôte n'en a
pas. Le secret est un secret SYSTÈME au sens de la skill `secrets` — c'est ce qui déclenche
la lecture qui décide de sa portée, et ici c'est une tâche sans personne.

**Fail closed, deux fois** : secret non configuré, tout est refusé ; secret présenté
différent, refusé. Un entretien qui ne tourne pas laisse un journal qui grossit ; une route
d'entretien ouverte laisse n'importe qui RETIRER des partitions.
"""

from __future__ import annotations

import hmac

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from miles_socle.auth.context import client_origin
from miles_socle.journal.maintenance import JournalMaintenance, MaintenanceReport

log = structlog.get_logger(__name__)

router = APIRouter()

MAINTENANCE_PATH = "/api/journal/maintenance"
BEARER = "bearer"
CHALLENGE = 'Bearer realm="miles-journal"'


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


def _presented(authorization: str | None) -> str | None:
    """Le jeton d'un en-tête `Authorization: Bearer`. Tout autre schéma ne présente rien.

    Même règle que les clés d'API (`apikeys/presentation.py`) : un schéma inattendu ne se
    rattrape pas en lisant la valeur quand même, sinon un `Basic` mal formé finirait
    comparé à notre secret.
    """
    presentee = (authorization or "").strip()
    if not presentee:
        return None
    schema, _, valeur = presentee.partition(" ")
    if schema.lower() != BEARER:
        return None
    return valeur.strip() or None


def _refuse(request: Request, raison: str) -> HTTPException:
    log.warning("journal_entretien_refuse", raison=raison, origin=client_origin(request))
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="jeton_requis",
        headers={"WWW-Authenticate": CHALLENGE},
    )


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
    if not attendu:
        # Non configuré : la route est inerte, et elle le DIT au journal. Rendre 503
        # « non configuré » distinguerait une stack sans jeton d'une stack avec, ce qui
        # renseigne un appelant qui n'a rien à savoir.
        raise _refuse(request, "non_configure")
    presente = _presented(request.headers.get("authorization"))
    # compare_digest et non `==` : la comparaison d'un secret ne doit pas s'arrêter au
    # premier caractère qui diffère.
    if presente is None or not hmac.compare_digest(presente, attendu):
        raise _refuse(request, "jeton_invalide")
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
