from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from environnement.identity.model import AssignedEnvironmentView

# Ce que ce produit rend EN PLUS du demandeur générique. L'identité, le pair, la demande
# et l'état de l'appariement sont au socle (`miles_socle.pairing.api_schemas`), qui sert
# les deux demandeurs ; ne reste ici que l'environnement assigné, dont le module de
# paramétrage n'a que faire.


class AssignedEnvironmentOut(BaseModel):
    """L'environnement rattaché, et QUAND on l'a appris. Les trois vont ensemble.

    La date voyage avec la valeur plutôt qu'à côté : un écran qui recevrait l'une sans
    l'autre afficherait un repli comme une lecture fraîche, et c'est exactement ce que le
    ticket 2edf1f3c interdit.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    label: str
    fetched_at: datetime


class AssignedEnvironmentViewOut(BaseModel):
    """Ce que l'écran reçoit : la valeur, et si elle vient d'être relue chez le pair.

    `fresh` ne se déduit PAS de `environment` : « le pair est injoignable et on n'a jamais
    rien su » et « le pair dit qu'aucun environnement ne nous est rattaché » rendent tous
    deux `environment: null`, et les confondre annoncerait « aucun environnement » à un
    administrateur dont le réseau est coupé.
    """

    model_config = ConfigDict(extra="forbid")

    environment: AssignedEnvironmentOut | None
    fresh: bool


def assigned_environment_out(vue: AssignedEnvironmentView) -> AssignedEnvironmentViewOut:
    return AssignedEnvironmentViewOut(
        environment=(
            None
            if vue.environment is None
            else AssignedEnvironmentOut(
                slug=vue.environment.slug,
                label=vue.environment.label,
                fetched_at=vue.environment.fetched_at,
            )
        ),
        fresh=vue.fresh,
    )
