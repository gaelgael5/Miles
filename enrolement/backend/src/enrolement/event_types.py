from __future__ import annotations

from miles_socle.cultures import service as cultures_events
from miles_socle.oidc import service as oidc_events
from miles_socle.secrets import service as secrets_events
from miles_socle.signing import identity_model as module_identity_events

from enrolement.environments import model as environment_events
from enrolement.pairing import model as pairing_events


def code_event_types() -> frozenset[str]:
    """Les types d'event connus du code, chaque module apportant les siens.

    Les types du socle, ceux de l'identité du module, ceux de l'appariement et ceux du
    référentiel des environnements. Le parc des devices et leur enrôlement viendront avec
    leurs propres tickets, et chacun ajoutera ses types ici. Le catalogue est injecté au
    journal plutôt que lu par lui : c'est ce qui permet au socle d'ignorer les events de
    ses consommateurs.
    """
    return frozenset(
        cultures_events.EVENT_TYPES
        | oidc_events.EVENT_TYPES
        | secrets_events.EVENT_TYPES
        | module_identity_events.EVENT_TYPES
        | pairing_events.EVENT_TYPES
        | environment_events.EVENT_TYPES
    )
