from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

from miles_socle.events.catalog import EventShape, closed_block
from miles_socle.signing.protocol import PeerSpecies

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
# Les connexions git confiées par le module de paramétrage (ticket edcf78bc, critère 11).
# Le genre d'objet est la CONNEXION et non le pair pour le renouvellement : « quand le
# credential de celle-ci a-t-il changé ? » se lit par l'objet, et c'est la question qu'on
# posera le jour où une lecture de git échoue. La transmission, elle, porte sur le pair :
# c'est un état complet qui arrive, pas une connexion qui bouge.
GIT_CONNECTION_OBJECT_KIND = "confided_git_connection"
GIT_CONNECTIONS_CONFIDED_EVENT = "pairing.git_connections_confided"
GIT_CREDENTIAL_RENEWED_EVENT = "pairing.git_credential_renewed"
# --- Les formes, c'est-à-dire le bloc de propriétés que chaque fait porte -------------
# Mesurées sur les producteurs eux-mêmes le 12/11/2026, un par un : ce fichier ne décrit
# pas ce qu'on aimerait écrire, il décrit ce que les cinq parties du service écrivent.
# Les blocs sont FERMÉS — ajouter une propriété sans la déclarer ici fait refuser l'event
# au lieu de la laisser entrer sans que l'écran ni le contrat n'en sachent rien.

_EMPREINTE: Mapping[str, Any] = {"type": "string", "minLength": 1}
# DÉRIVÉE du contrat, jamais recopiée : l'espèce voyage dans la chaîne signée, et une
# troisième espèce ajoutée là-bas doit entrer ici toute seule.
_ESPECE: Mapping[str, Any] = {"type": "string", "enum": list(get_args(PeerSpecies))}
# L'environnement est nommé par son identifiant ET par ses deux noms du moment : c'est
# sous le nom de l'époque qu'on relira ce journal, et les deux noms sont renommables.
_ENVIRONNEMENT: Mapping[str, Mapping[str, Any]] = {
    "environment_id": {"type": "string", "minLength": 1},
    "environment_slug": {"type": "string", "minLength": 1},
    "environment_label": {"type": "string", "minLength": 1},
}


_ENVIRONNEMENT_POSE = closed_block(_ENVIRONNEMENT)
# Le déplacement porte les SIX champs : il y avait quelque chose avant, et c'est ce
# « avant » qu'on viendra chercher. Les champs du précédent sont ABSENTS et non nuls dans
# les deux autres faits — un rattachement qui porterait `previous_environment_id: null`
# ferait chercher un déplacement qui n'a pas eu lieu, et le bloc fermé l'interdit.
_ENVIRONNEMENT_DEPLACE = closed_block(
    {
        **_ENVIRONNEMENT,
        **{f"previous_{nom}": forme for nom, forme in _ENVIRONNEMENT.items()},
    }
)

EVENT_SHAPES = (
    EventShape(
        REQUEST_OPENED_EVENT,
        "Demande d'appariement ouverte",
        closed_block(
            {
                "public_key_fingerprint": _EMPREINTE,
                "declared_name": {"type": "string", "minLength": 1},
                "species": _ESPECE,
            }
        ),
    ),
    # Refus et expiration ne portent rien : l'objet de l'event est l'origine de la
    # demande, et le fait est entier. Ce qu'elle déclarait se relit dans son ouverture.
    EventShape(REQUEST_REJECTED_EVENT, "Demande d'appariement refusée", closed_block({})),
    EventShape(REQUEST_EXPIRED_EVENT, "Demande d'appariement expirée", closed_block({})),
    EventShape(
        PAIRING_CONFIRMED_EVENT,
        "Appariement conclu",
        closed_block({"public_key_fingerprint": _EMPREINTE, "species": _ESPECE}),
    ),
    EventShape(
        ENVIRONMENT_DESIGNATED_EVENT, "Environnement désigné par une demande", _ENVIRONNEMENT_POSE
    ),
    EventShape(ENVIRONMENT_ATTACHED_EVENT, "Environnement rattaché", _ENVIRONNEMENT_POSE),
    EventShape(ENVIRONMENT_MOVED_EVENT, "Appariement déplacé", _ENVIRONNEMENT_DEPLACE),
    EventShape(
        PAIRING_REVOKED_EVENT,
        "Appariement révoqué",
        closed_block(
            {
                "public_key_fingerprint": _EMPREINTE,
                # NULS pour un appariement hérité, qui n'en portait aucun : les trois
                # champs sont là, et c'est leur nullité qui dit « aucun environnement ».
                **{nom: {"type": ["string", "null"]} for nom in _ENVIRONNEMENT},
                # `null` ET RIEN D'AUTRE, tant que le référentiel des devices n'existe
                # pas : écrire 0 serait indiscernable, dans un an, d'un vrai « aucun
                # device n'a été libéré ». Ce schéma rougira le jour où le référentiel
                # arrivera, et c'est le bon moment pour y penser.
                "devices_released": {"type": "null"},
                # Un entier, et non nul : les connexions git confiées existent, et un
                # environnement n'en porte jamais — la base le lui interdit. Zéro est
                # donc une vérité ici, là où pour les devices il aurait été un mensonge.
                "git_connections_destroyed": {"type": "integer", "minimum": 0},
            }
        ),
    ),
    EventShape(
        PEER_CONTACT_CHANGED_EVENT,
        "Adresse de contact du pair changée",
        closed_block({"contact_url": {"type": "string", "minLength": 1}}),
    ),
    EventShape(
        GIT_CONNECTIONS_CONFIDED_EVENT,
        "Connexions git confiées",
        closed_block(
            {
                "revision": {"type": "integer", "minimum": 0},
                # Les IDENTIFIANTS, jamais les credentials — pas même tronqués. Le journal
                # est lu bien plus largement que la table des connexions.
                "connections": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "renewed": {"type": "array", "items": {"type": "string", "minLength": 1}},
                "destroyed": {"type": "array", "items": {"type": "string", "minLength": 1}},
            }
        ),
    ),
    EventShape(
        GIT_CREDENTIAL_RENEWED_EVENT,
        "Credential git renouvelé",
        closed_block(
            {
                "peer_base_url": {"type": "string", "minLength": 1},
                "revision": {"type": "integer", "minimum": 0},
            }
        ),
    ),
)
# DÉRIVÉ des formes, jamais recopié : deux listes auraient divergé au premier type ajouté,
# et la plus courte aurait fait refuser au journal un event que ce module écrit.
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)
