from __future__ import annotations

from miles_socle.cultures import service as cultures_events
from miles_socle.events.catalog import EventCatalog, introduced_by
from miles_socle.events.categories import of_slug
from miles_socle.oidc import service as oidc_events
from miles_socle.secrets import service as secrets_events
from miles_socle.signing import identity_model as module_identity_events

from enrolement.environments import model as environment_events
from enrolement.hosting import model as hosting_events
from enrolement.pairing import events as pairing_events

# C'est CE produit qui introduit ces events, et la catégorie le dit. Elle n'est pas dans
# les modules du socle : cultures, OIDC, secrets et identité de module sont produits par
# les trois produits, et `culture.activated` est `backoffice-configuration` au portail
# pendant qu'il est `backoffice-enrolement` ici. Une seule déclaration, deux catégories.
CATEGORY = of_slug("backoffice-enrolement")


def code_event_catalog() -> EventCatalog:
    """Les types d'event connus du code, chaque module apportant les siens.

    Les types du socle, ceux de l'identité du module, ceux de l'appariement, ceux du
    référentiel des environnements et ceux de la version hébergée. Le parc des devices et
    leur enrôlement viendront avec leurs propres tickets, et chacun ajoutera ses formes
    ici. Le catalogue est injecté au journal plutôt que lu par lui : c'est ce qui permet
    au socle d'ignorer les events de ses consommateurs.

    Chaque module déclare la FORME de ses types — libellé et schéma du bloc de
    propriétés — et non plus leur seul nom (story `07aeebcd`, 12/11/2026). Le journal
    refuse donc un bloc non conforme en nommant la propriété fautive, là où il ne
    vérifiait que l'existence du type. Un catalogue faux fait tomber le démarrage, ce qui
    est le bon moment pour l'apprendre.
    """
    return EventCatalog(
        introduced_by(
            CATEGORY,
            cultures_events.EVENT_SHAPES,
            oidc_events.EVENT_SHAPES,
            secrets_events.EVENT_SHAPES,
            module_identity_events.EVENT_SHAPES,
            pairing_events.EVENT_SHAPES,
            environment_events.EVENT_SHAPES,
            hosting_events.EVENT_SHAPES,
        )
    )
