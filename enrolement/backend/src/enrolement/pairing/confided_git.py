from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from miles_socle.secrets.model import Secret, SecretUndecipherableError
from miles_socle.signing.protocol import ConfidedGitConnection

from enrolement.pairing.confided_git_model import (
    ConfidedConnectionDetail,
    ConfidedConnectionUnknownError,
    ConfidedGitSpeciesError,
    ConfidedGitStaleRevisionError,
    ConfidedGitState,
    NoParametragePairedError,
    validate_connection_id,
    validate_forge_url,
    validate_label,
    validate_repo_url,
    validate_workspace_id,
)
from enrolement.pairing.events import (
    GIT_CONNECTION_OBJECT_KIND,
    GIT_CONNECTIONS_CONFIDED_EVENT,
    GIT_CREDENTIAL_RENEWED_EVENT,
    PEER_OBJECT_KIND,
)
from enrolement.pairing.peer_reads import PairingPeerReads
from enrolement.pairing.store_confided_git import (
    db_delete_absent_connections,
    db_delete_workspaces,
    db_get_confided,
    db_get_revision,
    db_get_sealed,
    db_get_state_row,
    db_insert_workspaces,
    db_list_confided,
    db_lock_confided,
    db_parametrage_peer,
    db_upsert_connection,
    db_upsert_state,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ConfidingOutcome:
    """Ce que la réception a fait, pour que l'autre bout n'ait pas à croire son intention."""

    revision: int
    held: int
    destroyed: int


@dataclass(frozen=True)
class _Entree:
    """Une connexion validée, prête à écrire. Le credential n'existe ici qu'en mémoire."""

    id: str
    label: str
    base_url: str
    credential: Secret
    workspaces: list[tuple[str, str | None]]


class PairingConfidedGit(PairingPeerReads):
    """Les connexions git que le module de paramétrage CONFIE à ce module (ticket edcf78bc).

    Ce module les DÉTIENT pour le compte des environnements, et c'est la décision de
    sécurité qui porte le ticket : « le secret s'arrête au module d'enrôlement ». Un module
    d'environnement n'en reçoit jamais — il lira git par le relais —, ce qui donne deux
    propriétés : un environnement compromis ne livre pas l'accès au dépôt, et un
    environnement révoqué perd son accès à git sans qu'on révoque rien chez la forge.

    Trois gardes, et aucune ne remplace les autres : l'appel est signé par la clé du pair
    apparié ; l'espèce du pair est vérifiée ici, nommément ; et la base refuse par une clé
    étrangère composée qu'une connexion confiée appartienne à autre chose qu'un module de
    paramétrage. Le critère 10 exige que ça tienne au niveau des données.
    """

    async def resolve_receive_git_connections(
        self,
        *,
        declared_origin: str | None,
        signature: str | None,
        method: str,
        target: str,
        body: bytes,
        revision: int,
        connections: tuple[ConfidedGitConnection, ...],
    ) -> ConfidingOutcome:
        """Reçoit l'ÉTAT COMPLET des connexions git du module de paramétrage.

        L'état et non un écart : une transmission manquée est réparée par la suivante, et
        la suppression d'une connexion n'a pas de message à elle — absente de l'état, elle
        est détruite (critère 9).

        Tout est validé AVANT la transaction : une charge dont la dixième connexion est
        malformée ne doit pas laisser les neuf premières écrites et l'état à l'ancienne
        révision, état qu'aucun des deux côtés ne saurait décrire.
        """
        pair = await self.resolve_verify_incoming(
            declared_origin=declared_origin,
            signature=signature,
            method=method,
            target=target,
            body=body,
        )
        if pair.species != "parametrage":
            # Fail closed, et c'est l'interdit central du ticket. Nommé plutôt qu'opaque :
            # on ne l'atteint qu'avec la signature d'un pair apparié, qui n'apprend donc
            # rien qu'il ne sache déjà, et un refus muet lui ferait chercher ses clés.
            raise ConfidedGitSpeciesError(
                f"{pair.base_url} est apparié comme « {pair.species} » :"
                " seul un module de paramétrage confie des connexions git"
            )
        entrees = [_valide(connexion) for connexion in connections]
        maintenant = self.now()
        async with self.pool.acquire() as conn, conn.transaction():
            # Verrou d'abord : deux transmissions simultanées liraient la même révision
            # détenue, et la plus ancienne pourrait écrire après la plus récente.
            await db_lock_confided(conn, pair.base_url)
            detenue = await db_get_revision(conn, pair.base_url)
            if detenue is not None and revision < detenue:
                raise ConfidedGitStaleRevisionError(detenue, revision)
            renouvelees = await self._ecrit(conn, pair.base_url, pair.species, entrees, maintenant)
            detruites = await db_delete_absent_connections(
                conn, pair.base_url, [entree.id for entree in entrees]
            )
            await db_upsert_state(conn, pair.base_url, pair.species, revision, maintenant)
            await self.module.write_event(
                conn,
                GIT_CONNECTIONS_CONFIDED_EVENT,
                PEER_OBJECT_KIND,
                pair.base_url,
                {
                    "revision": revision,
                    # Les IDENTIFIANTS, jamais les credentials — pas même tronqués, pas
                    # même en cas d'erreur (interdit du ticket). Le journal est lu bien
                    # plus largement que cette table.
                    "connections": [entree.id for entree in entrees],
                    "renewed": renouvelees,
                    "destroyed": detruites,
                },
            )
            for connection_id in renouvelees:
                # Un event par renouvellement, en plus du compte ci-dessus : « quand le
                # credential de CETTE connexion a-t-il changé ? » se lit par l'objet, et
                # c'est la question qu'on posera le jour où une lecture de git échoue.
                await self.module.write_event(
                    conn,
                    GIT_CREDENTIAL_RENEWED_EVENT,
                    GIT_CONNECTION_OBJECT_KIND,
                    connection_id,
                    {"peer_base_url": pair.base_url, "revision": revision},
                )
        log.info(
            "connexions_git_confiees",
            base_url=pair.base_url,
            revision=revision,
            held=len(entrees),
            renewed=len(renouvelees),
            destroyed=len(detruites),
        )
        return ConfidingOutcome(revision, len(entrees), len(detruites))

    async def _ecrit(
        self, conn: Any, peer_base_url: str, species: str, entrees: list[_Entree], maintenant: Any
    ) -> list[str]:
        """Écrit les connexions et rend celles dont le credential a changé."""
        # Toute la liste du pair d'abord, parce qu'un workspace qui PASSE d'une connexion à
        # une autre resterait sinon sur les deux et ferait échouer son insertion.
        await db_delete_workspaces(conn, peer_base_url)
        renouvelees: list[str] = []
        for entree in entrees:
            renouvele = await self._credential_a_change(conn, peer_base_url, entree)
            await db_upsert_connection(
                conn,
                peer_base_url,
                species,
                entree.id,
                entree.label,
                entree.base_url,
                # Données associées = le pair ET la connexion : recopié sur une autre
                # ligne, le chiffré ne s'ouvre plus.
                self.cipher.seal(_aad(peer_base_url, entree.id), entree.credential),
                maintenant,
                renouvele,
            )
            await db_insert_workspaces(conn, peer_base_url, entree.id, entree.workspaces)
            if renouvele:
                renouvelees.append(entree.id)
        return renouvelees

    async def _credential_a_change(self, conn: Any, peer_base_url: str, entree: _Entree) -> bool:
        """Le credential diffère-t-il de celui qu'on détenait ? Comparé en mémoire, jamais écrit.

        La comparaison a lieu parce que le RENOUVELLEMENT est le cas d'usage principal du
        ticket : sans elle, une transmission qui ne change rien daterait un renouvellement
        qui n'a pas eu lieu, et la date qu'on viendra lire ne décrirait plus rien.

        Un chiffré illisible compte comme un changement : on le remplace de toute façon, et
        le dire au journal vaut mieux que de le traiter comme identique à ce qui arrive.
        """
        scelle = await db_get_sealed(conn, peer_base_url, entree.id)
        if scelle is None:
            # Connexion neuve : ce n'est pas un renouvellement, c'est un premier confiage.
            return False
        try:
            ancien = self.cipher.open(_aad(peer_base_url, entree.id), scelle)
        except SecretUndecipherableError:
            log.warning(
                "credential_confie_illisible_remplace",
                base_url=peer_base_url,
                connection=entree.id,
            )
            return True
        # `Secret.__eq__` compare en temps constant ; aucune des deux valeurs ne sort d'ici.
        return ancien != entree.credential

    async def resolve_confided_git_state(self) -> ConfidedGitState:
        """Ce que ce module détient, pour l'écran de son administrateur. Jamais un credential.

        `peer_base_url` nul veut dire « aucun module de paramétrage apparié », et c'est le
        critère 7 : l'écran le DIT, au lieu de montrer une liste vide qui se lirait comme
        une forge en panne ou une transmission perdue.
        """
        peer_base_url = await db_parametrage_peer(self.pool)
        if peer_base_url is None:
            # Vide par construction : les connexions confiées disparaissent en cascade avec
            # l'appariement. Rien à lire, et rien à purger d'un état précédent.
            return ConfidedGitState(None, None, None, ())
        etat = await db_get_state_row(self.pool, peer_base_url)
        connexions = await db_list_confided(self.pool, peer_base_url)
        return ConfidedGitState(
            peer_base_url,
            None if etat is None else etat[0],
            None if etat is None else etat[1],
            connexions,
        )

    async def resolve_confided_connection(self, connection_id: str) -> ConfidedConnectionDetail:
        """Le détail d'une connexion confiée, et si son credential est lisible ICI.

        Les deux refus sont nommés, et c'est ce que demandent les critères 7 et 9 : « aucun
        module de paramétrage apparié » et « cette connexion a été supprimée à la source »
        ne se lisent pas pareil, et ni l'un ni l'autre ne doit ressembler à une panne de la
        forge. Le credential, lui, est ouvert pour savoir s'il s'ouvre — et oublié.
        """
        validate_connection_id(connection_id)
        peer_base_url = await db_parametrage_peer(self.pool)
        if peer_base_url is None:
            raise NoParametragePairedError(
                "aucun module de paramétrage n'est apparié : aucune connexion git"
                " ne lui a été confiée"
            )
        connexion = await db_get_confided(self.pool, peer_base_url, connection_id)
        if connexion is None:
            raise ConfidedConnectionUnknownError(connection_id, peer_base_url)
        scelle = await db_get_sealed(self.pool, peer_base_url, connection_id)
        lisible = self._lisible(peer_base_url, connection_id, scelle)
        return ConfidedConnectionDetail(connexion, lisible)

    def _lisible(self, peer_base_url: str, connection_id: str, scelle: Any) -> bool:
        if scelle is None:  # pragma: no cover - la ligne et son chiffré naissent ensemble
            return False
        try:
            self.cipher.open(_aad(peer_base_url, connection_id), scelle)
        except SecretUndecipherableError:
            log.warning(
                "credential_confie_illisible", base_url=peer_base_url, connection=connection_id
            )
            return False
        return True

def _aad(peer_base_url: str, connection_id: str) -> str:
    """Les données associées du chiffrement : le pair ET la connexion.

    Elles lient le chiffré à sa ligne. Recopié sur une autre connexion — ou sur la ligne
    d'un autre pair après un ré-appariement — il ne s'ouvre plus, et c'est préférable à une
    valeur qui s'ouvrirait là où elle n'a rien à faire.
    """
    return f"{peer_base_url}/git-connection/{connection_id}"


def _valide(connexion: ConfidedGitConnection) -> _Entree:
    """Valide une connexion transmise AVANT tout usage en base. Le refus nomme le champ."""
    workspaces = [
        (validate_workspace_id(workspace.id), validate_repo_url(workspace.repo_url))
        for workspace in connexion.workspaces
    ]
    return _Entree(
        validate_connection_id(connexion.id),
        validate_label(connexion.label),
        validate_forge_url(connexion.base_url),
        # Déballé ici, au bord, et reballé immédiatement dans le `Secret` du socle : c'est
        # lui qui masque la valeur dans toute représentation textuelle.
        Secret(connexion.credential.get_secret_value()),
        workspaces,
    )
