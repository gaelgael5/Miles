from __future__ import annotations

from miles_socle.cultures import service as cultures_events
from miles_socle.oidc import service as oidc_events
from miles_socle.secrets import service as secrets_events
from miles_socle.signing import identity_model as module_identity_events

from environnement.apikeys import model as api_keys_events
from environnement.hosting import model as hosting_events
from environnement.identity import service as identity_events
from environnement.storages import model as storages_events


def code_event_types() -> frozenset[str]:
    """Les types d'event connus du code, chaque module apportant les siens.

    Les types du socle, ceux de l'identité du module, ceux du paramétrage servi
    (story 3bbd4f87) et ceux des tables de storage qu'il matérialise. Le reste du
    métier — entrées, sorties — viendra avec ses propres tickets, et
    chacun ajoutera ses types ici. Le catalogue est injecté au journal plutôt que lu par lui :
    c'est ce qui permet au socle d'ignorer les events de ses consommateurs.
    """
    return frozenset(
        cultures_events.EVENT_TYPES
        | oidc_events.EVENT_TYPES
        | secrets_events.EVENT_TYPES
        | module_identity_events.EVENT_TYPES
        | identity_events.EVENT_TYPES
        | hosting_events.EVENT_TYPES
        | storages_events.EVENT_TYPES
        | api_keys_events.EVENT_TYPES
    )
