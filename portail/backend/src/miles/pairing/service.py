from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from miles_socle.events.model import EventAuthor
from miles_socle.pairing.events import EVENT_TYPES as EVENT_TYPES
from miles_socle.pairing.model import EnrolmentPeer
from miles_socle.pairing.service import PairingRequesterService
from miles_socle.signing.protocol import PeerSpecies

# Tout l'appariement vient du socle (`miles_socle.pairing`) : c'est le MÊME mécanisme que
# celui du module d'environnement, et le ticket ba44914b l'interdit explicitement en
# double — « si celui de l'environnement ne se réemploie pas tel quel, c'est qu'il est à
# généraliser, pas à dupliquer ». Ce fichier ne contient donc que ce que le portail
# DÉCLARE ÊTRE, et la conséquence que l'appariement a POUR LUI SEUL.

SIGNING_KEY_LABEL = "Clé privée de signature du module de paramétrage"
# Ce que ce module répond dans l'échange de vivacité, et l'espèce qu'il déclare en
# frappant. « parametrage » sans accent ni espace : la valeur voyage dans un corps signé et
# entre dans un CHECK de base, où une forme stable vaut mieux qu'une forme lisible — le
# libellé lisible est à l'écran, traduit.
MODULE_NAME = "parametrage"


@dataclass(frozen=True)
class PairingService(PairingRequesterService):
    """Le demandeur du socle, plus la seule conséquence qui n'appartienne qu'au portail.

    Le module d'environnement, lui, étend le même service pour tenir l'environnement que
    l'enrôlement lui assigne. Le portail ne reçoit pas de devices : ce qu'il reçoit, c'est
    le DROIT DE CONFIER ses connexions git (ticket edcf78bc), et c'est pourquoi un
    appariement conclu les transmet aussitôt.
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
    # Ce qu'un appariement tout juste conclu déclenche ICI. Un rappel optionnel plutôt
    # qu'un appel direct au service qui confie, parce que celui-ci a besoin de CE
    # service-là pour signer : l'appeler par son nom ferait un cycle à la construction.
    # Le câblage passe une fermeture qui le relit sur l'application au moment de l'appel.
    #
    # Au socle ? Non : confier des connexions git est une conséquence du PORTAIL, pas du
    # protocole. Le module d'environnement n'a rien à transmettre en s'appariant, et lui
    # faire porter un rappel toujours nul rendrait le socle responsable d'une chose qu'il
    # ne sait pas nommer.
    on_paired: Callable[[EventAuthor], Awaitable[None]] | None = None

    async def resolve_confirm_pairing(self, author: EventAuthor, code: str) -> EnrolmentPeer:
        """Conclut l'appariement, puis confie aussitôt les connexions git déjà saisies.

        APRÈS l'appariement, et non en même temps : la transmission exige la clé du pair,
        qui n'arrive qu'avec cette réponse. Et sans jamais faire échouer l'appariement —
        le rappel avale ses propres pannes, parce qu'un appariement conclu des deux côtés
        ne doit pas se lire comme un échec chez nous.

        C'est ce qui rend vrai le critère 1 du ticket edcf78bc pour les connexions
        déclarées AVANT l'appariement : elles sont disponibles « sans aucune ressaisie », et
        sans geste de plus non plus.
        """
        pair = await super().resolve_confirm_pairing(author, code)
        if self.on_paired is not None:
            await self.on_paired(author)
        return pair
