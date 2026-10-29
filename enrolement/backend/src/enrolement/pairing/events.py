from __future__ import annotations

# Les types d'events de CE module et les objets qu'ils nomment, plus le libellé de son
# secret de signature. Dans leur propre fichier parce que les cinq parties du service en
# écrivent et que `event_types.py` les relit : les laisser dans `model.py`, qui porte les
# refus et les formes, y mélangeait deux choses qu'on ne relit jamais pour la même raison.

SIGNING_KEY_LABEL = "Clé privée de signature du module d'enrôlement"
# Ce module nomme l'environnement « pair » dans un seul sens : il en apparie N. La
# réciproque est fausse et doit le rester — un environnement n'a qu'un module
# d'enrôlement, parce que ce module est l'autorité UNIQUE sur l'affectation de ses devices.
PEER_OBJECT_KIND = "environment_peer"
REQUEST_OBJECT_KIND = "pairing_request"

REQUEST_OPENED_EVENT = "pairing.request_opened"
REQUEST_REJECTED_EVENT = "pairing.request_rejected"
REQUEST_EXPIRED_EVENT = "pairing.request_expired"
PAIRING_CONFIRMED_EVENT = "pairing.confirmed"
# Deux types et non un seul, parce que ce sont deux gestes : désigner l'environnement
# d'une demande encore ouverte — révocable en changeant d'avis —, et rattacher un
# appariement DÉJÀ conclu qui n'en avait pas. Les fondre rendrait impossible de retrouver
# combien d'appariements hérités restaient à rattacher.
ENVIRONMENT_DESIGNATED_EVENT = "pairing.environment_designated"
ENVIRONMENT_ATTACHED_EVENT = "pairing.environment_attached"
# Et un troisième, pour la même raison : DÉPLACER un appariement conclu d'un environnement
# vers un autre. Ce n'est pas un rattachement — il y avait quelque chose avant, et c'est ce
# « avant » qu'on viendra chercher. Un seul type portant un champ « ancien » parfois nul
# obligerait à lire la charge utile pour savoir lequel des deux gestes on relit.
ENVIRONMENT_MOVED_EVENT = "pairing.environment_moved"
# La révocation. Un type à elle, et non un `pairing.confirmed` avec un drapeau : c'est la
# trace qu'on cherchera le jour où des devices ne démarrent plus, et on la cherchera par
# son nom.
PAIRING_REVOKED_EVENT = "pairing.revoked"
# Changer l'adresse où l'on joint une stack est une DÉCISION, pas un réglage : c'est
# la seule chose que ce module compose vers l'extérieur, et il faut pouvoir dire qui
# l'a changée le jour où un avis part ailleurs qu'on ne croit.
PEER_CONTACT_CHANGED_EVENT = "pairing.peer_contact_changed"
EVENT_TYPES = frozenset(
    {
        REQUEST_OPENED_EVENT,
        REQUEST_REJECTED_EVENT,
        REQUEST_EXPIRED_EVENT,
        PAIRING_CONFIRMED_EVENT,
        ENVIRONMENT_DESIGNATED_EVENT,
        ENVIRONMENT_ATTACHED_EVENT,
        ENVIRONMENT_MOVED_EVENT,
        PAIRING_REVOKED_EVENT,
        PEER_CONTACT_CHANGED_EVENT,
    }
)
