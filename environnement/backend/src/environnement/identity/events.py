from __future__ import annotations

# Les types d'events de CE module. Dans leur propre fichier parce que les trois parties du
# service en écrivent, et que `service.py` les importe lui aussi : les y laisser ferait un
# cycle d'imports le jour du découpage. `event_types.py` les relit par `service`, qui les
# réexporte — l'import extérieur n'a pas bougé.
PEER_REGISTERED_EVENT = "module.peer_registered"
PAIRING_REQUESTED_EVENT = "module.pairing_requested"
PAIRING_CANCELLED_EVENT = "module.pairing_cancelled"
EVENT_TYPES = frozenset({PEER_REGISTERED_EVENT, PAIRING_REQUESTED_EVENT, PAIRING_CANCELLED_EVENT})
PEER_OBJECT_KIND = "enrolment_peer"
ATTEMPT_OBJECT_KIND = "pairing_attempt"
