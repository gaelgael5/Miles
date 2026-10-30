from __future__ import annotations

from miles_socle.cultures import service as cultures_events
from miles_socle.oidc import service as oidc_events
from miles_socle.pairing import events as pairing_events
from miles_socle.secrets import service as secrets_events
from miles_socle.signing import identity_model as module_identity_events

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
from miles.workshop import branches as branches_events
from miles.workshop import domains_service as domains_events
from miles.workshop import holds as holds_events
from miles.workshop import service as workshop_events
from miles.workshop import shelving as shelving_events
from miles.workshop import trads_service as trads_events
from miles.workspaces import cultures as workspace_cultures_events
from miles.workspaces import model as workspace_events


def code_event_types() -> frozenset[str]:
    """Les types d'event connus du code, chaque module apportant les siens.

    Le catalogue déclaré dans git viendra avec son propre ticket (3f4905bf) ; d'ici là,
    c'est cette union qui fait foi.
    """
    return frozenset(
        apikeys_events.EVENT_TYPES
        | chains_events.EVENT_TYPES
        | contracts_events.EVENT_TYPES
        | contract_models_events.EVENT_TYPES
        | cultures_events.EVENT_TYPES
        | datamodels_events.EVENT_TYPES
        | confide_events.EVENT_TYPES
        | gitaccess_events.EVENT_TYPES
        | identities_events.EVENT_TYPES
        | oauth_events.EVENT_TYPES
        | module_identity_events.EVENT_TYPES
        | country_events.EVENT_TYPES
        | oidc_events.EVENT_TYPES
        | pairing_events.EVENT_TYPES
        | secrets_events.EVENT_TYPES
        | security_events.EVENT_TYPES
        | sources_events.EVENT_TYPES
        | storages_events.EVENT_TYPES
        | branches_events.EVENT_TYPES
        | domains_events.EVENT_TYPES
        | holds_events.EVENT_TYPES
        | workshop_events.EVENT_TYPES
        | shelving_events.EVENT_TYPES
        | trads_events.EVENT_TYPES
        | workspace_cultures_events.EVENT_TYPES
        | workspace_events.EVENT_TYPES
    )
