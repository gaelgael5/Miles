from __future__ import annotations

from miles_socle.cultures import service as cultures_events
from miles_socle.events.catalog import EventCatalog, introduced_by
from miles_socle.events.categories import of_slug
from miles_socle.oidc import service as oidc_events
from miles_socle.secrets import service as secrets_events
from miles_socle.signing import identity_model as module_identity_events

from environnement.apikeys import model as api_keys_events
from environnement.hosting import model as hosting_events
from environnement.identity import service as identity_events
from environnement.ingestion import cleanup as cleanup_events
from environnement.ingestion import model as ingestion_events
from environnement.ingestion import trial as trial_events
from environnement.ingestion import writeback as writeback_events
from environnement.storages import model as storages_events

# C'est CE produit qui introduit ces events, et la catégorie le dit. Elle n'est pas dans
# les modules du socle : cultures, OIDC, secrets, identité de module et côté demandeur de
# l'appariement sont produits par plusieurs produits, et le même type n'a donc pas la même
# catégorie partout. Une seule déclaration, une catégorie par produit.
CATEGORY = of_slug("backoffice-environnement")


def code_event_catalog() -> EventCatalog:
    """Les types d'event connus du code, chaque module apportant les siens.

    Les types du socle, ceux de l'identité du module, ceux du paramétrage servi
    (story 3bbd4f87) et ceux des tables de storage qu'il matérialise. Le reste du métier —
    entrées, sorties — viendra avec ses propres tickets, et chacun ajoutera ses formes ici.
    Le catalogue est injecté au journal plutôt que lu par lui : c'est ce qui permet au
    socle d'ignorer les events de ses consommateurs.

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
            identity_events.EVENT_SHAPES,
            hosting_events.EVENT_SHAPES,
            storages_events.EVENT_SHAPES,
            api_keys_events.EVENT_SHAPES,
            ingestion_events.EVENT_SHAPES,
            trial_events.EVENT_SHAPES,
            writeback_events.EVENT_SHAPES,
            cleanup_events.EVENT_SHAPES,
        )
    )
