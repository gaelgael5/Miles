from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, NoReturn

import asyncpg
import httpx
import structlog
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from miles_socle.events.model import EventAuthor, EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.service import SecretsService
from miles_socle.signing.calls import (
    ORIGIN_HEADER,
    SIGNATURE_HEADER,
    CallSignatureError,
    origin_for_log,
    sign_call,
    validate_origin,
    verify_call,
)
from miles_socle.signing.identity import ModuleIdentityService
from miles_socle.signing.identity_model import (
    SINGLETON,
    ModuleIdentity,
    OriginMissingError,
)
from miles_socle.signing.keys import fingerprint, parse_public_key
from miles_socle.signing.peers import (
    IdentityInputError,
    validate_base_url,
    validate_declared_name,
    validate_public_key,
)
from miles_socle.signing.protocol import (
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PAIRING_STATUS_PATH,
    PEER_PING_PATH,
    PING_BODY,
)

from environnement.identity.model import (
    SIGNING_KEY_LABEL,
    EnrolmentPeer,
    PairingAttempt,
    PairingAttemptMissingError,
    PairingRefusedByPeerError,
    PeerClockSkewError,
    PeerMissingError,
    PeerRefusedError,
    PeerUnexpectedResponseError,
)
from environnement.identity.store import (
    db_delete_attempt,
    db_get_attempt,
    db_get_peer,
    db_upsert_attempt,
    db_upsert_peer,
)

log = structlog.get_logger(__name__)

PEER_REGISTERED_EVENT = "module.peer_registered"
PAIRING_REQUESTED_EVENT = "module.pairing_requested"
PAIRING_CANCELLED_EVENT = "module.pairing_cancelled"
EVENT_TYPES = frozenset({PEER_REGISTERED_EVENT, PAIRING_REQUESTED_EVENT, PAIRING_CANCELLED_EVENT})
_PEER_OBJECT_KIND = "enrolment_peer"
_ATTEMPT_OBJECT_KIND = "pairing_attempt"
# Le code recopié par l'humain : six chiffres, et rien d'autre. Validé AVANT de partir sur
# le réseau — c'est une saisie, et l'envoyer tel quel ferait porter au pair la validation
# d'une entrée qui est la nôtre.
_CODE_RE = re.compile(r"^[0-9]{6}$")
# Dérive annoncée par le pair, bornée avant d'être relue : c'est la réponse d'un autre
# service, et un entier démesuré n'a pas à traverser jusqu'à un écran.
_MAX_DRIFT_S = 7 * 24 * 3600
# Un pair lent ne doit pas retenir une requête d'administration indéfiniment.
PEER_HTTP_TIMEOUT_S = 5.0


# Les codes de refus sont des mots courts en minuscules. Borner la FORME avant de
# journaliser : ce qui arrive là est la réponse d'un autre service, pas la nôtre.
_PEER_DETAIL_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def _peer_detail(reponse: httpx.Response) -> str:
    """Le code de refus que le pair donne, si c'en est un. Sinon une marque, jamais son corps."""
    try:
        detail = reponse.json().get("detail")
    except ValueError:
        return "(corps illisible)"
    if isinstance(detail, str) and _PEER_DETAIL_RE.match(detail):
        return detail
    return "(sans code)"


# Les états que l'écran d'appariement doit distinguer. « En attente » et « échoué » ne
# peuvent pas être confondus : un écran qui les mélange fait recommencer la demande
# indéfiniment, ou fait attendre une acceptation qui ne viendra jamais.
PairingStateName = Literal[
    "non_apparie", "en_attente", "apparie", "refusee", "expiree", "pair_injoignable"
]


@dataclass(frozen=True)
class PairingState:
    """Où en est l'appariement, vu de ce module. Les deux moitiés, pas seulement l'état.

    `attempt` et `peer` sont rendus ENSEMBLE parce qu'un ré-appariement les fait coexister :
    l'appariement courant tient encore pendant qu'une nouvelle demande attend. Un écran qui
    ne verrait que l'état remplacerait l'un par l'autre avant que l'humain n'ait tranché.
    """

    state: PairingStateName
    attempt: PairingAttempt | None
    peer: EnrolmentPeer | None


@dataclass(frozen=True)
class PeerPong:
    """Ce que rend l'échange de vivacité, dans un sens comme dans l'autre."""

    module: str
    # Celle du PAIR, telle qu'il la déclare. Nulle s'il ne connaît pas son adresse publique.
    origin: str | None
    verified_key_fingerprint: str
    own_key_fingerprint: str


@dataclass(frozen=True)
class IdentityService:
    """L'identité du module et son pair unique : ce que l'environnement ajoute au socle.

    La paire de clés, son secret et son contrôle de cohérence viennent du socle
    (`ModuleIdentityService`) — l'enrôlement emploie exactement le même code, et c'est la
    condition pour que les deux bouts signent et vérifient la même chose. Ce qui est ici
    est ce qui n'appartient qu'à l'environnement : son pair UNIQUE, et les deux sens de
    l'échange avec lui.
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
                self.pool, self.secrets, self.cipher, self.catalog, self.now, SIGNING_KEY_LABEL
            ),
        )

    async def resolve_identity(self) -> ModuleIdentity:
        return await self.module.resolve_identity()

    async def resolve_private_key(self) -> Ed25519PrivateKey:
        return await self.module.resolve_private_key()

    async def resolve_peer(self) -> EnrolmentPeer:
        pair = await db_get_peer(self.pool)
        if pair is None:
            raise PeerMissingError("aucun module d'enrôlement apparié")
        return pair

    async def resolve_register_peer(
        self,
        author: EventAuthor,
        base_url: str,
        public_key: str,
        declared_name: str | None = None,
    ) -> EnrolmentPeer:
        """Enregistre le module d'enrôlement apparié, ou REMPLACE celui qui existe.

        Jamais un second pair : le modèle n'en admet qu'un, le module d'enrôlement étant
        l'autorité unique sur l'affectation des devices. C'est aussi par ici que passe le
        dépôt de clé à l'issue de l'appariement, et c'est voulu — un seul endroit écrit le
        pair, qu'un humain l'ait saisi ou que le protocole l'ait rapporté.
        """
        base_url, public_key = validate_base_url(base_url), validate_public_key(public_key)
        async with self.pool.acquire() as conn, conn.transaction():
            pair = await db_upsert_peer(conn, base_url, public_key, self.now(), declared_name)
            await self.module.write_event(
                conn,
                PEER_REGISTERED_EVENT,
                _PEER_OBJECT_KIND,
                SINGLETON,
                {"base_url": base_url, "public_key_fingerprint": fingerprint(public_key)},
                author=author,
            )
        log.info(
            "pair_enregistre", base_url=base_url, public_key_fingerprint=fingerprint(public_key)
        )
        return pair

    async def resolve_verify_incoming(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
    ) -> EnrolmentPeer:
        """Vérifie un appel entrant, ou lève. Point d'application du fail closed de ce produit.

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

    async def resolve_ping_peer(self) -> PeerPong:
        """Émet un appel signé vers le pair : l'autre sens du même échange."""
        pair = await self.resolve_peer()
        reponse = await self.post_signed(pair.base_url, PEER_PING_PATH, PING_BODY)
        if reponse.status_code == 401:
            # Distingué d'une panne de réseau : le pair a répondu, et il nous refuse. Le
            # statut seul ne dit pas POURQUOI — son portillon d'authentification et son
            # vérificateur de signature rendent le même 401 —, d'où son code de refus dans
            # le journal. Jamais son corps entier : c'est la réponse d'un autre service.
            log.warning(
                "ping_refuse_par_le_pair",
                base_url=pair.base_url,
                peer_detail=_peer_detail(reponse),
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

    async def post_signed(self, base_url: str, path: str, body: bytes) -> httpx.Response:
        """POST signé par la clé privée du module. Seul endroit qui compose l'appel sortant.

        `base_url` est une origine SANS chemin : la cible signée et le chemin de la requête
        coïncident donc, ce qui est la condition pour que le pair vérifie exactement la
        chaîne qu'on a signée.
        """
        origine = self.origin
        if origine is None:
            raise OriginMissingError("MILES_PUBLIC_URL absente : le module ne peut pas signer")
        privee = await self.resolve_private_key()
        entete = sign_call(privee, origin=origine, method="POST", target=path, body=body)
        return await self.http.post(
            f"{base_url}{path}",
            content=body,
            headers={
                ORIGIN_HEADER: origine,
                SIGNATURE_HEADER: entete,
                "Content-Type": "application/json",
            },
        )

    async def resolve_attempt(self) -> PairingAttempt:
        """La demande d'appariement en cours. Pour que l'écran sache chez qui on a frappé."""
        tentative = await db_get_attempt(self.pool)
        if tentative is None:
            raise PairingAttemptMissingError("aucune demande d'appariement en cours")
        return tentative

    async def resolve_request_pairing(
        self, author: EventAuthor, enrolment_base_url: str, name: str
    ) -> PairingAttempt:
        """Frappe chez le module d'enrôlement et y dépose NOTRE clé publique.

        Premier des deux dépôts. L'appel est signé par notre clé privée, et le pair le
        vérifie contre la clé publique que ce corps porte : cela ne dit pas qui nous
        sommes — un humain le dira avec le code — mais cela prouve que nous détenons bien
        la privée de la publique déposée. Sans quoi n'importe qui déposerait la clé d'un
        autre sous une origine qu'il ne contrôle pas.

        Aucune clé privée ne figure dans ce corps, et il n'en existe aucun champ.
        """
        base_url = validate_base_url(enrolment_base_url)
        # Saisie d'un administrateur : validée ICI, avant de partir. L'envoyer telle quelle
        # ferait porter au pair la validation d'une entrée qui est la nôtre.
        name = validate_declared_name(name)
        identite = await self.resolve_identity()
        corps = json.dumps({"public_key": identite.public_key, "name": name}).encode("utf-8")
        reponse = await self.post_signed(base_url, PAIRING_REQUEST_PATH, corps)
        if reponse.status_code != 202:
            self._refuse_peer(reponse, base_url)
        maintenant = self.now()
        echeance = _peer_expires_at(reponse)
        async with self.pool.acquire() as conn, conn.transaction():
            tentative = await db_upsert_attempt(conn, base_url, maintenant, name, echeance)
            await self.module.write_event(
                conn,
                PAIRING_REQUESTED_EVENT,
                _ATTEMPT_OBJECT_KIND,
                SINGLETON,
                {
                    "base_url": base_url,
                    "declared_name": name,
                    "public_key_fingerprint": fingerprint(identite.public_key),
                },
                author=author,
            )
        log.info("appariement_demande", base_url=base_url)
        return tentative

    async def resolve_confirm_pairing(self, author: EventAuthor, code: str) -> EnrolmentPeer:
        """Présente le code recopié, et range la clé publique que le pair rend en retour.

        Second dépôt : à l'issue, chacun détient sa clé privée et la clé publique de
        l'autre, et plus aucun appel entre les deux ne demande d'intervention humaine.
        """
        code = _validate_code(code)
        tentative = await self.resolve_attempt()
        corps = json.dumps({"code": code}).encode("utf-8")
        reponse = await self.post_signed(tentative.base_url, PAIRING_CONFIRM_PATH, corps)
        if reponse.status_code != 200:
            self._refuse_peer(reponse, tentative.base_url)
        charge = reponse.json()
        # La clé rendue par le pair est une entrée venue du réseau : validée avant d'être
        # écrite, et avant tout usage comme vérificateur de ses appels.
        public_key = validate_public_key(str(charge["public_key"]))
        base_url = validate_base_url(str(charge["base_url"]))
        pair = await self.resolve_register_peer(author, base_url, public_key, tentative.name)
        async with self.pool.acquire() as conn, conn.transaction():
            # La tentative disparaît APRÈS que le pair est écrit : l'ordre inverse
            # laisserait, sur une panne entre les deux, ni pair ni demande — donc un
            # appariement à refaire depuis le début sans que rien ne le dise.
            await db_delete_attempt(conn)
        log.info(
            "appariement_conclu",
            base_url=base_url,
            peer_key_fingerprint=fingerprint(public_key),
        )
        return pair

    async def resolve_pairing_state(self) -> PairingState:
        """L'état complet de l'appariement, celui que l'écran rend lisible.

        Sans demande en cours, il se lit localement. Avec une demande en cours, il faut
        DEMANDER AU PAIR : son refus d'un code et la disparition de la demande rendent le
        même refus opaque — volontairement —, donc rien d'ici ne distinguerait « un humain
        n'a pas encore répondu » de « un humain a dit non ».

        Le pair ne dit que « en attente » ou « inconnue ». C'est NOUS qui tranchons entre
        refusée et expirée, en comparant à l'échéance qu'il nous a annoncée en accusant la
        demande : nous détenons les deux moitiés, lui n'en détient qu'une.
        """
        pair = await db_get_peer(self.pool)
        tentative = await db_get_attempt(self.pool)
        if tentative is None:
            return PairingState("apparie" if pair else "non_apparie", None, pair)
        try:
            reponse = await self.post_signed(tentative.base_url, PAIRING_STATUS_PATH, PING_BODY)
        except (httpx.HTTPError, OriginMissingError):
            # Injoignable n'est pas « refusée » : faire recommencer la demande pour une
            # panne de réseau détruirait un appariement en cours d'acceptation.
            log.warning("etat_d_appariement_indisponible", base_url=tentative.base_url)
            return PairingState("pair_injoignable", tentative, pair)
        disparue = _demande_disparue(reponse)
        if disparue is None:
            log.warning(
                "etat_d_appariement_indisponible",
                base_url=tentative.base_url,
                status_code=reponse.status_code,
                peer_detail=_peer_detail(reponse),
            )
            return PairingState("pair_injoignable", tentative, pair)
        if not disparue:
            return PairingState("en_attente", tentative, pair)
        if tentative.expires_at is None:
            # Sans échéance connue, on ne tranche pas : dire « refusée » quand on ne sait
            # pas enverrait chercher un humain qui n'a rien fait.
            return PairingState("expiree", tentative, pair)
        return PairingState(
            "expiree" if self.now() >= tentative.expires_at else "refusee", tentative, pair
        )

    async def resolve_cancel_attempt(self, author: EventAuthor) -> None:
        """Abandonne la demande en cours. Le pair, lui, laissera la sienne expirer."""
        async with self.pool.acquire() as conn, conn.transaction():
            if not await db_delete_attempt(conn):
                raise PairingAttemptMissingError("aucune demande d'appariement en cours")
            await self.module.write_event(
                conn, PAIRING_CANCELLED_EVENT, _ATTEMPT_OBJECT_KIND, SINGLETON, {}, author=author
            )
        log.info("appariement_annule")

    def _refuse_peer(self, reponse: httpx.Response, base_url: str) -> NoReturn:
        """Traduit le refus du pair sans rien inventer de ce qu'il n'a pas dit."""
        if reponse.status_code == 409:
            derive = _peer_drift_s(reponse)
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
                peer_detail=_peer_detail(reponse),
            )
            raise PairingRefusedByPeerError("le module d'enrôlement a refusé l'appariement")
        log.warning(
            "reponse_inattendue_du_pair", base_url=base_url, status_code=reponse.status_code
        )
        raise PeerUnexpectedResponseError(reponse.status_code)

    def _refuse(self, reason: str, declared_origin: str) -> NoReturn:
        log.warning("appel_signe_refuse", reason=reason, declared_origin=declared_origin)
        raise CallSignatureError(reason)


def _validate_code(code: str) -> str:
    """Six chiffres, débarrassés de TOUT espace — pas seulement de ceux des bords.

    Un code circule par copier-coller : il arrive avec des espaces avant, après, et
    parfois au milieu, parce qu'on l'a lu « 314 159 » sur un écran qui l'aérait. Le
    refuser pour cela revient à refuser le bon code.

    Le nettoyage est ICI et pas seulement dans l'écran. Mesuré sur machine de test le
    28/10/2026 : seul le navigateur nettoyait, et un appel direct à l'API avec « 314 159 »
    rendait 422. Une règle qui ne vit que dans un écran est fausse pour tout autre
    appelant — et pour le prochain écran, qui l'oubliera.
    """
    code = "".join(code.split())
    if not _CODE_RE.match(code):
        raise IdentityInputError("code")
    return code


def _demande_disparue(reponse: httpx.Response) -> bool | None:
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
    if reponse.status_code == 401 and _peer_detail(reponse) == "appariement_refuse":
        return True
    return None


def _peer_expires_at(reponse: httpx.Response) -> datetime | None:
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


def _peer_drift_s(reponse: httpx.Response) -> int | None:
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
