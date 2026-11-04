from __future__ import annotations

from dataclasses import dataclass

from miles_socle.pairing.events import EVENT_TYPES as EVENT_TYPES
from miles_socle.pairing.events import PAIRING_CANCELLED_EVENT as PAIRING_CANCELLED_EVENT
from miles_socle.pairing.events import PAIRING_REQUESTED_EVENT as PAIRING_REQUESTED_EVENT
from miles_socle.pairing.events import PEER_REGISTERED_EVENT as PEER_REGISTERED_EVENT
from miles_socle.pairing.peer_calls import PEER_HTTP_TIMEOUT_S as PEER_HTTP_TIMEOUT_S
from miles_socle.pairing.peer_calls import PeerPong as PeerPong
from miles_socle.pairing.service import PairingRequesterService
from miles_socle.signing.protocol import PEER_PING_PATH as PEER_PING_PATH
from miles_socle.signing.protocol import PeerSpecies

from environnement.identity.assigned_environment import IdentityAssignedEnvironment
from environnement.identity.model import MODULE_NAME, SIGNING_KEY_LABEL

# Les réexports ci-dessus ne sont pas de la commodité : `event_types.py` et les tests de
# ce produit nomment ces valeurs, et les faire pointer vers le socle en un seul endroit
# évite que chaque appelant choisisse sa propre voie d'accès — après quoi un déplacement
# au socle se rattrape à dix endroits au lieu d'un.


@dataclass(frozen=True)
class IdentityService(PairingRequesterService, IdentityAssignedEnvironment):
    """Le demandeur du socle, plus ce que CE module tient en plus : l'environnement assigné.

    Aucun champ ajouté, aucune méthode redéfinie : tout l'appariement — frapper, coller le
    code, constater l'état, recevoir un avis de révocation — vient de
    `PairingRequesterService`, que le module de paramétrage emploie tel quel. Ce qui est
    ajouté ici est ce dont lui n'a que faire : à quel environnement du référentiel
    l'enrôlement nous a rattachés.

    Ce module ne CHOISIT pas son environnement et ne doit jamais pouvoir le faire : la
    décision appartient à un humain chez l'enrôlement, autorité unique sur l'affectation
    des devices.
    """

    # Ce que ce produit DÉCLARE ÊTRE, redéclaré ici avec sa valeur. Ce ne sont pas des
    # réglages : ni l'espèce ni le nom du module ne se configurent, et une stack qui
    # pourrait se déclarer autre chose ferait accepter à l'humain d'en face un appariement
    # dont les conséquences ne sont pas celles qu'il croit. Portées par la CLASSE plutôt
    # que par chaque site de câblage — production et harnais de test — parce que trois
    # constantes recopiées à deux endroits finissent par diverger, et que la divergence
    # serait verte.
    module_name: str = MODULE_NAME
    species: PeerSpecies = "environnement"
    key_label: str = SIGNING_KEY_LABEL
