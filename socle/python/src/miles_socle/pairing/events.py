from __future__ import annotations

# Les types d'events du côté DEMANDEUR de l'appariement, et les objets qu'ils nomment.
#
# Au socle avec le reste de ce côté du protocole (ticket ba44914b) : les deux demandeurs
# écrivent les mêmes faits, et deux catalogues de même contenu auraient divergé au premier
# type ajouté d'un seul côté — le produit qui ne l'aurait pas déclaré refuserait d'écrire
# l'event, et le refus apparaîtrait loin de sa cause.
#
# Les noms commencent par `module.` et non par le nom d'un produit, et c'est ce qui permet
# ce partage : ils disent « ce module » du point de vue de celui qui écrit. Chaque produit
# les joint à son propre catalogue dans son `event_types.py` — un type d'event absent du
# catalogue est refusé à l'écriture, et c'est voulu.
PEER_REGISTERED_EVENT = "module.peer_registered"
PAIRING_REQUESTED_EVENT = "module.pairing_requested"
PAIRING_CANCELLED_EVENT = "module.pairing_cancelled"
EVENT_TYPES = frozenset({PEER_REGISTERED_EVENT, PAIRING_REQUESTED_EVENT, PAIRING_CANCELLED_EVENT})
PEER_OBJECT_KIND = "enrolment_peer"
ATTEMPT_OBJECT_KIND = "pairing_attempt"
