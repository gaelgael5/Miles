from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

import httpx
import structlog
from miles_socle.signing.calls import post_signed
from miles_socle.signing.identity_model import OriginMissingError
from miles_socle.signing.protocol import PEER_PING_PATH, PING_BODY

from environnement.identity.base import IdentityBase
from environnement.identity.model import (
    EnrolmentPeer,
    PairingRefusedByPeerError,
    PairingStateName,
    PeerClockSkewError,
    PeerRefusedError,
    PeerUnexpectedResponseError,
)

log = structlog.get_logger(__name__)

# Dérive annoncée par le pair, bornée avant d'être relue : c'est la réponse d'un autre
# service, et un entier démesuré n'a pas à traverser jusqu'à un écran.
_MAX_DRIFT_S = 7 * 24 * 3600
# Un pair lent ne doit pas retenir une requête d'administration indéfiniment.
PEER_HTTP_TIMEOUT_S = 5.0
# Les codes de refus que seule une ROUTE DE PAIR produit. Un 401 nu ne prouve rien — le
# portillon d'authentification du pair en rend un aussi (mesuré le 28/10/2026) —, et c'est
# ce code dans le corps qui dit que la réponse vient d'un vérificateur de signature.
_REFUS_DE_SIGNATURE = frozenset({"signature_refusee", "appariement_refuse"})
# Les codes de refus sont des mots courts en minuscules. Borner la FORME avant de
# journaliser : ce qui arrive là est la réponse d'un autre service, pas la nôtre.
_PEER_DETAIL_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def peer_detail(reponse: httpx.Response) -> str:
    """Le code de refus que le pair donne, si c'en est un. Sinon une marque, jamais son corps."""
    try:
        detail = reponse.json().get("detail")
    except ValueError:
        return "(corps illisible)"
    if isinstance(detail, str) and _PEER_DETAIL_RE.match(detail):
        return detail
    return "(sans code)"


@dataclass(frozen=True)
class PeerPong:
    """Ce que rend l'échange de vivacité, dans un sens comme dans l'autre."""

    module: str
    # Celle du PAIR, telle qu'il la déclare. Nulle s'il ne connaît pas son adresse publique.
    origin: str | None
    verified_key_fingerprint: str
    own_key_fingerprint: str


class IdentityPeerCalls(IdentityBase):
    """Ce que ce module ENVOIE au pair, et comment il lit ce qui revient.

    Rassemblé ici parce que lire la réponse d'un autre service est un exercice à part : on
    y borne ce qui vient de lui avant de le relire, et on s'interdit d'en déduire plus
    qu'il n'en dit. Les trois issues — accepté, refusé, injoignable — ne se confondent
    jamais, et chacune appelle un geste différent.
    """

    async def post_signed(self, contact_url: str, path: str, body: bytes) -> httpx.Response:
        """POST signé par la clé privée du module. Délègue au socle depuis le 29/10/2026.

        La composition elle-même est au socle (`miles_socle.signing.calls.post_signed`)
        parce qu'un DEUXIÈME produit en a besoin : le module d'enrôlement, qui prévient
        une stack qu'il lui révoque l'accès. Ce qui reste ici est ce qui n'appartient
        qu'à ce module — sa clé privée, relue à chaque appel, et son origine configurée.
        """
        origine = self.origin
        if origine is None:
            raise OriginMissingError("MILES_PUBLIC_URL absente : le module ne peut pas signer")
        return await post_signed(
            self.http,
            await self.resolve_private_key(),
            origin=origine,
            contact_url=contact_url,
            path=path,
            body=body,
        )

    async def resolve_ping_peer(self) -> PeerPong:
        """Émet un appel signé vers le pair : l'autre sens du même échange."""
        pair = await self.resolve_peer()
        # L'adresse de CONTACT, pas l'identité : le pair peut se nommer ailleurs qu'où on
        # le joint, et composer son identité est exactement ce qui ne marchait plus dès
        # qu'un intermédiaire s'interposait.
        reponse = await self.post_signed(pair.contact_url, PEER_PING_PATH, PING_BODY)
        if reponse.status_code == 401:
            # Distingué d'une panne de réseau : le pair a répondu, et il nous refuse. Le
            # statut seul ne dit pas POURQUOI — son portillon d'authentification et son
            # vérificateur de signature rendent le même 401 —, d'où son code de refus dans
            # le journal. Jamais son corps entier : c'est la réponse d'un autre service.
            log.warning(
                "ping_refuse_par_le_pair",
                base_url=pair.base_url,
                peer_detail=peer_detail(reponse),
            )
            raise PeerRefusedError("le pair n'a pas accepté notre appel signé")
        if reponse.status_code != 200:
            # Il a répondu : ce n'est donc ni un problème de réseau ni un refus.
            log.warning(
                "reponse_inattendue_du_pair",
                base_url=pair.base_url,
                status_code=reponse.status_code,
            )
            raise PeerUnexpectedResponseError(reponse.status_code)
        charge = reponse.json()
        origine_du_pair = charge.get("origin")
        return PeerPong(
            module=str(charge["module"]),
            origin=None if origine_du_pair is None else str(origine_du_pair),
            verified_key_fingerprint=str(charge["verified_key_fingerprint"]),
            own_key_fingerprint=str(charge["own_key_fingerprint"]),
        )

    async def _peer_still_accepts_us(self, pair: EnrolmentPeer) -> PairingStateName:
        """Le pair accepte-t-il encore nos appels signés ? Trois issues, jamais deux.

        Un 401 NE SUFFIT PAS à conclure « révoqué » : mesuré le 28/10/2026, le portillon
        d'authentification du pair rend lui aussi 401 quand sa route de pair n'existe
        pas, et les deux ont la même forme. Ce qui distingue, c'est le code de refus que
        sa route de pair met dans son corps — lui seul vient d'un vérificateur de
        signature. Sans ce code, on retombe sur « injoignable », qui ne fait rien perdre.

        Et même avec lui, on ne nomme pas la cause : révocation chez lui ou clés qui ne se
        correspondent plus produisent le même refus, et il ne dit pas lequel. L'état dit
        ce qui est sûr — ses appels nous sont refusés — et l'écran propose de refrapper.
        """
        try:
            reponse = await self.post_signed(pair.contact_url, PEER_PING_PATH, PING_BODY)
        except (httpx.HTTPError, OriginMissingError):
            # Les DEUX au journal : « où croyait-on l'appeler ? » est la première
            # question d'un pair qu'on ne joint plus, et l'identité seule n'y répond pas.
            log.warning(
                "appariement_pair_injoignable",
                base_url=pair.base_url,
                contact_url=pair.contact_url,
            )
            return "pair_injoignable"
        if reponse.status_code == 200:
            return "apparie"
        detail = peer_detail(reponse)
        if reponse.status_code == 401 and detail in _REFUS_DE_SIGNATURE:
            log.warning(
                "appariement_refuse_par_le_pair", base_url=pair.base_url, peer_detail=detail
            )
            return "refuse_par_le_pair"
        log.warning(
            "appariement_etat_indisponible",
            base_url=pair.base_url,
            status_code=reponse.status_code,
            peer_detail=detail,
        )
        return "pair_injoignable"

    def _refuse_peer(self, reponse: httpx.Response, base_url: str) -> NoReturn:
        """Traduit le refus du pair sans rien inventer de ce qu'il n'a pas dit."""
        if reponse.status_code == 409:
            derive = peer_drift_s(reponse)
            if derive is not None:
                log.warning(
                    "appariement_horloges_desynchronisees", base_url=base_url, drift_s=derive
                )
                raise PeerClockSkewError(derive)
        if reponse.status_code in (401, 409):
            # Le pair ne dit pas LEQUEL des cas — code faux, demande inconnue, expirée,
            # brûlée, refusée — et c'est volontaire chez lui. Ne pas en choisir un ici :
            # une cause plausible mais fausse envoie chercher au mauvais endroit.
            log.warning(
                "appariement_refuse_par_le_pair",
                base_url=base_url,
                peer_detail=peer_detail(reponse),
            )
            raise PairingRefusedByPeerError("le module d'enrôlement a refusé l'appariement")
        log.warning(
            "reponse_inattendue_du_pair", base_url=base_url, status_code=reponse.status_code
        )
        raise PeerUnexpectedResponseError(reponse.status_code)


def demande_disparue(reponse: httpx.Response) -> bool | None:
    """La demande a-t-elle disparu de chez le pair ? `None` quand il n'a pas répondu à ça.

    Trois lectures, et la troisième est celle qui coûte le plus cher à se tromper :

    - **200 avec un état** : il répond, on le croit ;
    - **401 en disant `appariement_refuse`** : sa route de pair a parlé. Elle ne détient
      plus ni notre demande ni notre appariement, donc plus aucune clé pour vérifier
      l'appel, et elle refuse plutôt que de confirmer à un inconnu qu'une origine n'est
      pas appariée. NOUS savons que nous avions une demande : pour nous, c'est qu'elle a
      disparu. Le lire comme une panne afficherait « injoignable » là où un humain vient
      de refuser (trouvé par la campagne du 28/10/2026) ;
    - **tout autre 401** : ce n'est PAS sa route de pair qui parle, c'est son portillon
      d'authentification, qui rend 401 sur toute route `/api` inconnue. Autrement dit sa
      version ne sert pas encore cette route. `LESSONS.md` porte cette confusion depuis le
      28/10/2026 : un 401 d'un module Miles ne prouve rien tant qu'on n'a pas lu POURQUOI.
    """
    if reponse.status_code == 200:
        try:
            return str(reponse.json().get("state")) != "en_attente"
        except ValueError:
            return None
    if reponse.status_code == 401 and peer_detail(reponse) == "appariement_refuse":
        return True
    return None


def peer_expires_at(reponse: httpx.Response) -> datetime | None:
    """L'échéance que le pair annonce en accusant la demande, si elle est lisible.

    Bornée et typée avant d'être écrite : elle vient d'un autre service. `None` quand elle
    n'a pas la forme attendue — on préfère ne pas savoir trancher entre refusée et expirée
    plutôt que de trancher sur une date inventée.
    """
    try:
        brut = reponse.json().get("expires_at")
    except ValueError:
        return None
    if not isinstance(brut, str) or len(brut) > 40:
        return None
    try:
        echeance = datetime.fromisoformat(brut)
    except ValueError:
        return None
    # Une date sans fuseau est ambiguë, et la comparer à `now()` lèverait à l'exécution.
    return None if echeance.tzinfo is None else echeance


def peer_drift_s(reponse: httpx.Response) -> int | None:
    """La dérive d'horloge annoncée par le pair, si elle a la forme attendue.

    Bornée et typée avant toute relecture : ce nombre vient d'un autre service, et il
    finira sur un écran. `None` quand la réponse n'est pas celle qu'on croit, auquel cas
    l'appelant retombe sur le refus générique plutôt que d'inventer une cause.
    """
    try:
        charge = reponse.json()
    except ValueError:
        return None
    if charge.get("detail") != "horloges_desynchronisees":
        return None
    derive = charge.get("drift_s")
    if not isinstance(derive, int) or isinstance(derive, bool) or abs(derive) > _MAX_DRIFT_S:
        return None
    return derive
