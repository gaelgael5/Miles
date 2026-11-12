from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

from miles_socle.events.catalog import EventShape
from miles_socle.signing.protocol import PeerSpecies

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

# --- Les formes, mesurées sur `flow.py`, le seul producteur de ces trois faits ---------
# Partagées pour la même raison que les noms : les deux demandeurs écrivent les mêmes
# faits, et deux formes de même contenu auraient divergé au premier champ ajouté d'un seul
# côté. La CATÉGORIE, elle, n'est pas ici — c'est le produit qui l'introduit.
_ADRESSE: Mapping[str, Any] = {"type": "string", "minLength": 1}
_FORMES: Mapping[str, Mapping[str, Any]] = {
    PAIRING_REQUESTED_EVENT: {
        "base_url": _ADRESSE,
        "declared_name": {"type": "string", "minLength": 1},
        # Au journal parce que c'est ce qu'on a DÉCLARÉ être : le jour où un appariement
        # n'a pas les droits attendus, la première question est « sous quelle espèce
        # avions-nous frappé ? ». DÉRIVÉE du contrat, qui la fait voyager.
        "species": {"type": "string", "enum": list(get_args(PeerSpecies))},
        "public_key_fingerprint": {"type": "string", "minLength": 1},
    },
    PEER_REGISTERED_EVENT: {
        # Deux choses, et les confondre est l'erreur que le ticket ba44914b corrige :
        # `base_url` est l'IDENTITÉ du pair, `contact_url` l'ADRESSE où on le joint. Une
        # stack qu'on ne joint plus se diagnostique d'abord par « où croyait-on l'appeler ? ».
        "base_url": _ADRESSE,
        "public_key_fingerprint": {"type": "string", "minLength": 1},
        "contact_url": _ADRESSE,
    },
    # Rien : l'annulation est un fait entier, et la tentative annulée se relit dans sa
    # demande. Le bloc fermé dit qu'on n'y ajoute rien sans le déclarer.
    PAIRING_CANCELLED_EVENT: {},
}
_LIBELLES: Mapping[str, str] = {
    PAIRING_REQUESTED_EVENT: "Appariement demandé",
    PEER_REGISTERED_EVENT: "Module d'enrôlement enregistré",
    PAIRING_CANCELLED_EVENT: "Demande d'appariement annulée",
}
EVENT_SHAPES = tuple(
    EventShape(
        nom,
        _LIBELLES[nom],
        {
            "type": "object",
            "properties": dict(proprietes),
            "required": sorted(proprietes),
            "additionalProperties": False,
        },
    )
    for nom, proprietes in _FORMES.items()
)
# DÉRIVÉ des formes, jamais recopié : deux listes auraient divergé au premier type ajouté,
# et le produit qui ne l'aurait pas déclaré refuserait d'écrire l'event.
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)
PEER_OBJECT_KIND = "enrolment_peer"
ATTEMPT_OBJECT_KIND = "pairing_attempt"
