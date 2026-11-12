from __future__ import annotations

from miles_socle.cultures import service as cultures_events
from miles_socle.events.catalog import EventCatalog, introduced_by
from miles_socle.events.categories import of_slug
from miles_socle.oidc import service as oidc_events
from miles_socle.pairing import events as pairing_events
from miles_socle.secrets import service as secrets_events
from miles_socle.signing import identity_model as module_identity_events

from miles.accounts import service as accounts_events
from miles.apikeys import service as apikeys_events
from miles.chains import service as chains_events
from miles.contracts import models_service as contract_models_events
from miles.contracts import service as contracts_events
from miles.datamodels import service as datamodels_events
from miles.gitaccess import confide_model as confide_events
from miles.gitaccess import model as gitaccess_events
from miles.identities import service as identities_events
from miles.oauth import clients as oauth_events
from miles.reference import model as country_events
from miles.security import service as security_events
from miles.sources import service as sources_events
from miles.storages import service as storages_events
from miles.workflowevents import service as workflow_events_events
from miles.workshop import branches as branches_events
from miles.workshop import domains_service as domains_events
from miles.workshop import holds as holds_events
from miles.workshop import service as workshop_events
from miles.workshop import shelving as shelving_events
from miles.workshop import trads_keys as trads_keys_events
from miles.workshop import trads_service as trads_events
from miles.workspaces import cultures as workspace_cultures_events
from miles.workspaces import model as workspace_events

# C'est CE produit qui introduit ces events, et la catégorie le dit. Elle n'est pas dans
# les modules du socle : cultures, OIDC, secrets, identité de module et côté demandeur de
# l'appariement sont produits par plusieurs produits, et le même type n'a donc pas la même
# catégorie partout. Une seule déclaration, une catégorie par produit.
CATEGORY = of_slug("backoffice-configuration")


def code_event_catalog() -> EventCatalog:
    """Les types d'event connus du code, chaque module apportant les siens.

    Le catalogue déclaré dans git viendra avec son propre ticket (3f4905bf) ; d'ici là,
    c'est cette union qui fait foi.

    Chaque module déclare la FORME de ses types — libellé et schéma du bloc de
    propriétés — et non plus leur seul nom (story `07aeebcd`, 12/11/2026). Le journal
    refuse donc un bloc non conforme en nommant la propriété fautive, là où il ne
    vérifiait que l'existence du type. Un catalogue faux fait tomber le démarrage, ce qui
    est le bon moment pour l'apprendre.
    """
    return EventCatalog(
        introduced_by(
            CATEGORY,
            accounts_events.EVENT_SHAPES,
            apikeys_events.EVENT_SHAPES,
            chains_events.EVENT_SHAPES,
            contracts_events.EVENT_SHAPES,
            contract_models_events.EVENT_SHAPES,
            cultures_events.EVENT_SHAPES,
            datamodels_events.EVENT_SHAPES,
            confide_events.EVENT_SHAPES,
            gitaccess_events.EVENT_SHAPES,
            identities_events.EVENT_SHAPES,
            oauth_events.EVENT_SHAPES,
            module_identity_events.EVENT_SHAPES,
            country_events.EVENT_SHAPES,
            oidc_events.EVENT_SHAPES,
            pairing_events.EVENT_SHAPES,
            secrets_events.EVENT_SHAPES,
            security_events.EVENT_SHAPES,
            sources_events.EVENT_SHAPES,
            storages_events.EVENT_SHAPES,
            workflow_events_events.EVENT_SHAPES,
            branches_events.EVENT_SHAPES,
            domains_events.EVENT_SHAPES,
            holds_events.EVENT_SHAPES,
            workshop_events.EVENT_SHAPES,
            shelving_events.EVENT_SHAPES,
            trads_events.EVENT_SHAPES,
            trads_keys_events.EVENT_SHAPES,
            workspace_cultures_events.EVENT_SHAPES,
            workspace_events.EVENT_SHAPES,
        )
    )
