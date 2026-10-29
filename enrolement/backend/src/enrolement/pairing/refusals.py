from __future__ import annotations

from typing import Any, NoReturn

import structlog
from miles_socle.signing.calls import (
    CallSignatureError,
    origin_for_log,
    validate_origin,
    verify_call,
)
from miles_socle.signing.keys import parse_public_key

from enrolement.pairing.base import PairingBase
from enrolement.pairing.model import PairingRefusedError
from enrolement.pairing.store_peers import db_get_revocation

log = structlog.get_logger(__name__)


class PairingRefusals(PairingBase):
    """Comment ce module REFUSE, et ce qu'il en dit — au journal, jamais à l'appelant.

    Rassemblé ici parce que l'opacité des refus est une propriété d'ensemble, pas le
    détail d'une route : un seul refus pour tous les cas d'appariement impossible, et la
    raison précise au journal. La tenir en un endroit est ce qui rend lisible, d'un coup
    d'œil, qu'aucune route n'en dit davantage que les autres.
    """

    def _own_origin(self) -> str:
        if self.origin is None:
            # Sans adresse publique, l'environnement ne saurait pas quelle origine attendre
            # de nos appels, et les refuserait tous. Mieux vaut refuser l'appariement que
            # le conclure à moitié.
            raise PairingRefusedError("origine_locale_absente")
        return self.origin

    def _verified_origin(self, declared_origin: str | None, signature: str | None) -> str:
        """L'origine déclarée, validée. Les deux refus qui précèdent toute lecture de base."""
        origine_journal = origin_for_log(declared_origin)
        if not signature:
            # Avant l'origine, et l'ordre compte pour le JOURNAL : un appel sans aucune
            # signature n'est pas un appel signé mal présenté, c'est quelqu'un qui frappe
            # une route de pair sans savoir ce qu'elle attend. Journaliser
            # « origine_invalide » enverrait le diagnostic vers une origine mal configurée
            # alors qu'il n'y a rien du tout (mesuré le 28/10/2026 côté environnement).
            self._refuse("absente", origine_journal)
        try:
            return validate_origin(declared_origin or "")
        except CallSignatureError:
            self._refuse("origine_invalide", origine_journal)

    def _verify_or_refuse(
        self,
        public_key: str,
        signature: str | None,
        origin: str,
        method: str,
        target: str,
        body: bytes,
    ) -> None:
        try:
            verify_call(
                parse_public_key(public_key),
                signature,
                origin=origin,
                method=method,
                target=target,
                body=body,
            )
        except CallSignatureError as refus:
            self._refuse(refus.reason, origin)

    async def _refuse_unknown_origin(self, conn: Any, origin: str) -> NoReturn:
        """Refuse une origine sans appariement, en DISANT au journal si elle a été révoquée.

        La réponse servie est la même dans les deux cas, mot pour mot : distinguer
        offrirait un oracle — savoir qu'une origine a déjà été appariée, puis révoquée.
        Seule la ligne de journal change, et c'est tout l'objet du critère 4 : sans elle,
        un exploitant cherche une clé perdue ou une horloge alors qu'un humain a décidé.

        La lecture de la pierre tombale n'a lieu que sur ce chemin de REFUS : un appel
        d'un pair apparié ne la paie jamais.
        """
        if await db_get_revocation(conn, origin) is not None:
            self._refuse("origine_revoquee", origin)
        self._refuse("origine_inconnue", origin)

    def _refuse(self, reason: str, declared_origin: str) -> NoReturn:
        log.warning("appariement_refuse", reason=reason, declared_origin=declared_origin)
        raise PairingRefusedError(reason)
