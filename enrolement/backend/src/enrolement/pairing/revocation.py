from __future__ import annotations

import httpx
import structlog
from miles_socle.events.model import EventAuthor
from miles_socle.signing.calls import post_signed
from miles_socle.signing.identity_model import OriginMissingError
from miles_socle.signing.keys import fingerprint
from miles_socle.signing.peers import validate_base_url
from miles_socle.signing.protocol import PAIRING_REVOKED_PATH, REVOKED_BODY

from enrolement.pairing.base import PairingBase
from enrolement.pairing.events import (
    PAIRING_REVOKED_EVENT,
    PEER_CONTACT_CHANGED_EVENT,
    PEER_OBJECT_KIND,
)
from enrolement.pairing.model import (
    EnvironmentPeer,
    PeerNotFoundError,
)
from enrolement.pairing.store_peers import (
    db_delete_peer,
    db_record_revocation,
    db_set_peer_contact_url,
)

log = structlog.get_logger(__name__)


class PairingRevocation(PairingBase):
    """Rompre un appariement, et le DIRE à la stack qu'on rompt.

    Dans son propre fichier parce que c'est le seul endroit où ce module compose un appel
    SORTANT. Partout ailleurs il sert et répond ; ici il appelle, et les règles ne sont
    pas les mêmes — l'avis est au mieux, il ne conditionne rien, et l'adresse qu'il
    compose est saisie chez nous plutôt que déclarée par l'autre bout.
    """

    async def resolve_revoke_pairing(self, author: EventAuthor, base_url: str) -> EnvironmentPeer:
        """Révoque l'appariement : sa ligne disparaît, et la clé publique du pair avec elle.

        Le geste inverse de l'appariement, et il n'en est pas le symétrique : un
        environnement porte des devices, et ce qu'ils deviennent est une décision, pas un
        effet de bord. Elle est prise (ticket d5ffeb33) : ils sont REMIS EN ATTENTE
        d'affectation, jamais réaffectés vers un repli. « Un device qui ne démarre pas est
        un incident visible ; un device qui démarre sur les mauvaises données est un
        incident invisible. » Rien ici ne doit jamais ressembler à un repli.

        L'environnement, lui, RESTE au référentiel et redevient libre : la révocation
        porte sur l'appariement, pas sur l'environnement. Deux gestes qui n'ont pas les
        mêmes conséquences ne s'enchaînent pas tout seuls.
        """
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            revoque = await db_delete_peer(conn, base_url)
            if revoque is None:
                raise PeerNotFoundError(f"aucun environnement apparié sous {base_url}")
            empreinte = fingerprint(revoque.public_key)
            # Dans la MÊME transaction que la suppression : une pierre tombale sans
            # suppression dirait révoqué un appariement encore vivant, et une suppression
            # sans pierre tombale ferait journaliser « origine inconnue » le premier appel
            # du pair — soit exactement la fausse piste que le critère 4 interdit.
            await db_record_revocation(conn, base_url, empreinte, maintenant)
            await self.module.write_event(
                conn,
                PAIRING_REVOKED_EVENT,
                PEER_OBJECT_KIND,
                base_url,
                {
                    "public_key_fingerprint": empreinte,
                    # L'environnement quitté est nommé par son identifiant ET par ses deux
                    # noms du moment : c'est sous le nom de l'époque qu'on relira ce
                    # journal. Nul pour un appariement hérité, qui n'en portait aucun.
                    "environment_id": str(revoque.environment.id) if revoque.environment else None,
                    "environment_slug": (revoque.environment.slug if revoque.environment else None),
                    "environment_label": (
                        revoque.environment.label if revoque.environment else None
                    ),
                    # NUL, et jamais 0. Le référentiel des devices n'existe pas encore :
                    # écrire 0 serait indiscernable, dans un an, d'un vrai « aucun device
                    # n'a été libéré » — et c'est précisément cette ligne qu'on viendra
                    # lire le jour où des devices ne démarrent plus.
                    "devices_released": None,
                },
                author=author,
            )
        log.info(
            "appariement_revoque",
            base_url=base_url,
            peer_key_fingerprint=empreinte,
            environment_slug=revoque.environment.slug if revoque.environment else None,
        )
        # APRÈS que la révocation est commise, et AU MIEUX. Une stack éteinte, en panne ou
        # injoignable ne doit ni empêcher la révocation, ni la retarder au-delà du délai
        # du client, ni la faire échouer — c'est la crainte que portait le contrat quand
        # il refusait cet avis, et elle reste vraie. Ce que l'avis change, c'est que
        # l'écran d'en face NOMME la cause au lieu de l'énumérer.
        await self._notify_revoked(revoque)
        return revoque

    async def _notify_revoked(self, pair: EnvironmentPeer) -> None:
        """Dit à la stack qu'on vient de lui révoquer l'accès. Au mieux, jamais bloquant.

        Signé de NOTRE clé privée, que la révocation n'a pas touchée — c'est la sienne
        qu'on a détruite. Elle vérifie l'avis avec notre clé publique, qu'elle détient
        depuis l'appariement : personne n'apprend rien qu'il ne détienne déjà, et c'est
        ce qui rend cet avis possible là où une réponse serait un oracle.

        Composé vers l'adresse de CONTACT, que notre administrateur a saisie : l'origine
        déclarée d'une stack passe souvent par un intermédiaire qui ne nous laisse pas
        passer, et l'avis n'arriverait jamais.
        """
        if self.origin is None:
            # Sans adresse publique on ne sait pas signer, et un avis non signé serait
            # refusé — à juste titre. Le dire au journal plutôt que de l'émettre pour rien.
            log.warning("avis_de_revocation_non_emis", base_url=pair.base_url, reason="origine")
            return
        try:
            reponse = await post_signed(
                self.http,
                await self.module.resolve_private_key(),
                origin=self.origin,
                contact_url=pair.contact_url,
                path=PAIRING_REVOKED_PATH,
                body=REVOKED_BODY,
            )
        except (httpx.HTTPError, OriginMissingError) as panne:
            log.warning(
                "avis_de_revocation_non_remis",
                base_url=pair.base_url,
                contact_url=pair.contact_url,
                reason=type(panne).__name__,
            )
            return
        if reponse.status_code != 204:
            log.warning(
                "avis_de_revocation_refuse",
                base_url=pair.base_url,
                contact_url=pair.contact_url,
                status_code=reponse.status_code,
            )
            return
        log.info("avis_de_revocation_remis", base_url=pair.base_url)

    async def resolve_set_peer_contact_url(
        self, author: EventAuthor, base_url: str, contact_url: str
    ) -> EnvironmentPeer:
        """Change l'adresse où l'on joint cette stack. Son IDENTITÉ ne change pas.

        L'identité vient de la stack et entre dans ce qu'on vérifie d'elle ; l'adresse de
        contact est à nous, et n'entre dans aucune signature. C'est son administrateur à
        elle qui déclare la première, le nôtre qui saisit la seconde — laisser un tiers
        non authentifié désigner la cible de nos appels sortants reviendrait à lui confier
        ce que nous composons.
        """
        contact_url = validate_base_url(contact_url)
        async with self.pool.acquire() as conn, conn.transaction():
            pair = await db_set_peer_contact_url(conn, base_url, contact_url)
            if pair is None:
                raise PeerNotFoundError(f"aucun environnement apparié sous {base_url}")
            await self.module.write_event(
                conn,
                PEER_CONTACT_CHANGED_EVENT,
                PEER_OBJECT_KIND,
                base_url,
                {"contact_url": contact_url},
                author=author,
            )
        log.info("adresse_de_contact_changee", base_url=base_url, contact_url=contact_url)
        return pair
