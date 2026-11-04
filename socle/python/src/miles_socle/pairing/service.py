from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import asyncpg
import httpx
import structlog

from miles_socle.events.model import EventTypeCatalog
from miles_socle.pairing.flow import RequesterPairingFlow
from miles_socle.pairing.model import EnrolmentPeer
from miles_socle.pairing.status import RequesterPairingStatus
from miles_socle.pairing.store import db_get_peer
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.calls import (
    CallSignatureError,
    origin_for_log,
    validate_origin,
    verify_call,
)
from miles_socle.signing.identity import ModuleIdentityService
from miles_socle.signing.keys import parse_public_key
from miles_socle.signing.protocol import PeerSpecies

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class PairingRequesterService(RequesterPairingFlow, RequesterPairingStatus):
    """Le côté DEMANDEUR de l'appariement : un pair unique, et les deux sens de l'échange.

    Employé tel quel par le module de paramétrage, et ÉTENDU par le module
    d'environnement, qui tient en plus l'environnement que l'enrôlement lui assigne.
    C'est toute la décision du ticket ba44914b : « si celui de l'environnement ne se
    réemploie pas tel quel, c'est qu'il est à généraliser, pas à dupliquer ».

    UN pair, et le modèle le tient : le module d'enrôlement est l'autorité unique sur ce
    qu'on vient lui demander — des devices pour un environnement, des connexions git pour
    le module de paramétrage. Deux pairs voudraient dire deux autorités, et plus aucune
    réponse unique à « qui décide ».

    UNE classe, découpée en plusieurs fichiers par héritage — aucune indirection ajoutée à
    l'exécution. Les parties : les appels sortants et la lecture de ce qui revient, les
    gestes de l'appariement, et le constat de son état.
    """

    pool: asyncpg.Pool
    secrets: SecretsService
    cipher: SecretCipher
    catalog: EventTypeCatalog
    now: Callable[[], datetime]
    http: httpx.AsyncClient
    # Adresse publique du module, d'où l'origine qu'il déclare en signant. CONFIGURÉE
    # (MILES_PUBLIC_URL) et jamais lue des en-têtes : un `Host` forgé ferait signer pour
    # une origine qui n'est pas la nôtre.
    origin: str | None
    # Le nom que ce module se donne dans l'échange de vivacité, et l'espèce de demandeur
    # qu'il déclare en frappant. Les deux sont des CHAMPS et non des constantes de ce
    # fichier : il sert deux produits, et une valeur en dur y ferait répondre
    # « environnement » au module de paramétrage.
    module_name: str
    species: PeerSpecies
    # Nomme le module dans l'écran des secrets. « Une clé privée de signature » sans plus
    # de précision serait, sur une machine qui porte les trois stacks, indiscernable de
    # celle du voisin.
    key_label: str
    # Composé plutôt que reçu : les appelants (production et harnais de test) construisent
    # déjà ce service avec exactement ce qu'il faut au socle, et leur faire assembler les
    # deux ajouterait un câblage de plus à tenir d'accord — la panne que le socle a
    # justement supprimée.
    module: ModuleIdentityService = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "module",
            ModuleIdentityService(
                self.pool, self.secrets, self.cipher, self.catalog, self.now, self.key_label
            ),
        )

    async def resolve_verify_incoming(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> EnrolmentPeer:
        """Vérifie un appel entrant, ou lève. Point d'application du fail closed du demandeur.

        Tous les refus passent par ici et sont journalisés avec l'origine DÉCLARÉE —
        validée avant d'être écrite, parce qu'avant la vérification elle n'est encore
        qu'une entrée anonyme. Ce que l'appelant apprend, lui, se limite à « refusé ».
        """
        origine_journal = origin_for_log(declared_origin)
        pair = await db_get_peer(self.pool)
        if pair is None:
            self._refuse("aucun_pair", origine_journal)
        if not signature:
            # Avant l'origine, et l'ordre compte pour le JOURNAL : un appel sans aucune
            # signature n'est pas un appel signé mal présenté, c'est quelqu'un qui frappe
            # une route de pair sans savoir ce qu'elle attend. Mesuré le 28/10/2026 : en
            # validant l'origine d'abord, un appel entièrement nu était journalisé
            # « origine_invalide », ce qui envoie le diagnostic vers une origine mal
            # configurée alors qu'il n'y a rien du tout.
            self._refuse("absente", origine_journal)
        try:
            origine = validate_origin(declared_origin or "")
        except CallSignatureError:
            self._refuse("origine_invalide", origine_journal)
        if origine != pair.base_url:
            # L'origine déclarée doit être celle du pair apparié. Sans cette comparaison,
            # le champ ne servirait qu'à décorer le journal.
            self._refuse("origine_inattendue", origine_journal)
        try:
            verify_call(
                parse_public_key(pair.public_key),
                signature,
                origin=origine,
                method=method,
                target=target,
                body=body,
            )
        except CallSignatureError as refus:
            self._refuse(refus.reason, origine_journal)
        return pair
