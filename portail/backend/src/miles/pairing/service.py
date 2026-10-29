from __future__ import annotations

from dataclasses import dataclass

from miles_socle.pairing.events import EVENT_TYPES as EVENT_TYPES
from miles_socle.pairing.service import PairingRequesterService
from miles_socle.signing.protocol import PeerSpecies

# Tout l'appariement vient du socle (`miles_socle.pairing`) : c'est le MÊME mécanisme que
# celui du module d'environnement, et le ticket ba44914b l'interdit explicitement en
# double — « si celui de l'environnement ne se réemploie pas tel quel, c'est qu'il est à
# généraliser, pas à dupliquer ». Ce fichier ne contient donc que ce que le portail
# DÉCLARE ÊTRE, et il n'y a rien d'autre à écrire ici : c'est la mesure de la réussite de
# l'extraction, pas un oubli.

SIGNING_KEY_LABEL = "Clé privée de signature du module de paramétrage"
# Ce que ce module répond dans l'échange de vivacité, et l'espèce qu'il déclare en
# frappant. « parametrage » sans accent ni espace : la valeur voyage dans un corps signé et
# entre dans un CHECK de base, où une forme stable vaut mieux qu'une forme lisible — le
# libellé lisible est à l'écran, traduit.
MODULE_NAME = "parametrage"


@dataclass(frozen=True)
class PairingService(PairingRequesterService):
    """Le demandeur du socle, et rien de plus : le portail n'ajoute aucun geste.

    Le module d'environnement, lui, étend le même service pour tenir l'environnement que
    l'enrôlement lui assigne. Le portail ne reçoit pas de devices : il n'a rien de tel à
    retenir, et ce qu'il recevra — les connexions git — viendra avec le ticket edcf78bc.
    """

    # Ce que ce produit DÉCLARE ÊTRE. Ni l'espèce ni le nom du module ne se configurent :
    # une stack qui pourrait se déclarer autre chose ferait accepter à l'humain d'en face
    # un appariement dont les conséquences ne sont pas celles qu'il croit. Portés par la
    # CLASSE plutôt que par chaque site de câblage — production et harnais de test —
    # parce que trois constantes recopiées à deux endroits finissent par diverger, et que
    # la divergence serait verte.
    module_name: str = MODULE_NAME
    species: PeerSpecies = "parametrage"
    key_label: str = SIGNING_KEY_LABEL
