from __future__ import annotations

from miles_socle.cultures import service as cultures_events
from miles_socle.oidc import service as oidc_events
from miles_socle.secrets import service as secrets_events


def code_event_types() -> frozenset[str]:
    """Les types d'event connus du code, chaque module apportant les siens.

    La coquille n'a que les types du socle : l'enrôlement d'un device, le parc et
    l'appariement d'un environnement viendront avec leurs propres tickets, et chacun
    ajoutera ses types ici. Le catalogue est injecté au journal plutôt que lu par lui :
    c'est ce qui permet au socle d'ignorer les events de ses consommateurs.
    """
    return frozenset(
        cultures_events.EVENT_TYPES | oidc_events.EVENT_TYPES | secrets_events.EVENT_TYPES
    )
