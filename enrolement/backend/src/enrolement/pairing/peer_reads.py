from __future__ import annotations

import structlog

from enrolement.pairing.model import EnvironmentPeer, PairingRequest
from enrolement.pairing.refusals import PairingRefusals
from enrolement.pairing.store import db_get_request
from enrolement.pairing.store_peers import db_get_peer

log = structlog.get_logger(__name__)


class PairingPeerReads(PairingRefusals):
    """Ce qu'un pair LIT : vérifier son appel, et demander où en est sa demande.

    Séparé des deux gestes de l'appariement — frapper, confirmer — parce que ces deux-là
    écrivent, brûlent un secret et concluent, alors qu'ici on ne fait que vérifier et
    rendre. Le fichier est né de la limite de 300 lignes du dépôt, et la coupure a suivi
    cette frontière-là plutôt qu'un partage arbitraire.

    La règle d'opacité est la même des deux côtés : l'appelant est une machine, et rien de
    ce qu'il reçoit ne doit lui apprendre autre chose que « refusé ».
    """

    async def resolve_verify_incoming(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> EnvironmentPeer:
        """Vérifie l'appel d'un environnement DÉJÀ apparié. Point d'application du fail closed.

        Tous les refus passent par ici et sont journalisés avec l'origine DÉCLARÉE —
        validée avant d'être écrite, parce qu'avant la vérification elle n'est encore
        qu'une entrée anonyme. Ce que l'appelant apprend, lui, se limite à « refusé ».
        """
        origine = self._verified_origin(declared_origin, signature)
        pair = await db_get_peer(self.pool, origine)
        if pair is None:
            await self._refuse_unknown_origin(self.pool, origine)
        self._verify_or_refuse(pair.public_key, signature, origine, method, target, body)
        return pair

    async def resolve_request_state(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> PairingRequest | None:
        """Où en est la demande de l'appelant. Signée : chacun ne lit que la sienne.

        Vérifiée contre la clé que la demande porte — et, si elle a disparu, contre celle
        du pair déjà apparié, parce qu'un environnement qui vient d'être apparié demandera
        encore une fois où il en est avant de rafraîchir son écran. Sans ce second
        recours, sa dernière question serait refusée juste après son succès.

        Rend `None` pour « inconnue », sans dire si elle a été refusée ou si elle a
        expiré : ce module ne garde aucune trace d'une demande disparue. C'est l'appelant
        qui tranche, en comparant à l'échéance qu'il a reçue en frappant.
        """
        origine = self._verified_origin(declared_origin, signature)
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            await self._purge_expired(conn, maintenant)
            rangee = await db_get_request(conn, origine)
            pair = None if rangee is not None else await db_get_peer(conn, origine)
        cle = rangee[0].public_key if rangee is not None else (pair.public_key if pair else None)
        if cle is None:
            # Ni demande ni appariement : rien à dire, et surtout pas « inconnue », qui
            # confirmerait à un inconnu que cette origine n'est pas déjà appariée.
            await self._refuse_unknown_origin(self.pool, origine)
        self._verify_or_refuse(cle, signature, origine, method, target, body)
        return None if rangee is None else rangee[0]
