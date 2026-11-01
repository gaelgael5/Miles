"""Recevoir l'ordre de servir une version, aller chercher le contenu, et se mettre à jour.

C'est le « que le system se mette à jour » de la demande de Gael du 01/11/2026. Ce module
ne CHOISIT rien : la version est choisie chez l'enrôlement, par un humain, et il n'existe
ici aucun chemin pour en décider une autre — comme pour l'environnement assigné, l'autorité
est d'un seul côté.

**L'ordre est poussé, le contenu est tiré.** C'est le sens choisi par Gael, et ce fichier
en porte la conséquence utile : ce module VA CHERCHER le bundle chez l'enrôlement, sur un
appel qu'il signe. Il ne parle jamais à la forge, et ne détient aucun credential git.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog
from miles_socle.pairing.model import PeerMissingError
from miles_socle.signing.hosting import (
    HOSTING_BUNDLE_PATH,
    HOSTING_HTTP_TIMEOUT_S,
    MAX_BUNDLE_BYTES,
    HostedVersionIn,
    HostedVersionOut,
    HostingBundleIn,
)
from miles_socle.signing.identity_model import OriginMissingError

from environnement.hosting.gitstore import HostedTree
from environnement.hosting.model import (
    HOSTING_OBJECT_KIND,
    REFUSAL_NO_ORIGIN,
    REFUSAL_NO_PEER,
    REFUSAL_RELAY_REFUSED,
    REFUSAL_RELAY_UNREACHABLE,
    REFUSAL_TOO_LARGE,
    VERSION_REFUSED_EVENT,
    VERSION_SERVED_EVENT,
    BundleRejectedError,
)
from environnement.hosting.store import (
    db_get_hosted_version,
    db_record_order,
    db_record_refusal,
    db_record_served,
)
from environnement.identity.service import IdentityService

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HostingService:
    """La version que cette stack sert, et le trajet qui l'y amène.

    Tient le service d'identité plutôt que de l'étendre : ce qu'il lui emprunte est l'appel
    signé et le pair apparié, pas son métier. L'inverse aurait fait porter à l'appariement
    une responsabilité qu'il ne sait pas nommer.
    """

    identity: IdentityService
    tree: HostedTree

    async def resolve_order(self, ordre: HostedVersionIn) -> HostedVersionOut:
        """Enregistre l'ordre, amène le contenu si besoin, et rend ce qu'on SERT.

        **Ce qui décide s'il y a du travail est l'ARBRE, pas la table.** Un redéploiement
        remplace les images sans toucher au volume, mais un volume neuf — première
        installation, disque perdu — laisserait la table affirmer qu'on sert une version
        dont il ne reste rien. Interroger git est ce qui rend l'ordre rejoué utile : c'est
        le geste de réparation que l'enrôlement propose à son administrateur.

        Un ordre identique ET un arbre conforme ne déclenchent aucune récupération, et
        n'écrivent aucun event : rien ne s'est passé, et le journal ne doit pas dire le
        contraire.
        """
        maintenant = self.identity.now()
        async with self.identity.pool.acquire() as conn, conn.transaction():
            await db_record_order(conn, ordre.workspace_id, ordre.number, ordre.commit, maintenant)
        servi = await self.tree.head()
        if servi == ordre.commit:
            await self._marque_servi(ordre.commit, journalise=False)
            return await self._vue(ordre)
        refus = await self._amene(ordre)
        if refus is not None:
            async with self.identity.pool.acquire() as conn, conn.transaction():
                await db_record_refusal(conn, refus)
                await self._write_event(conn, VERSION_REFUSED_EVENT, ordre, {"refusal": refus})
            log.warning(
                "version_non_servie",
                workspace_id=ordre.workspace_id,
                number=ordre.number,
                refusal=refus,
            )
            return await self._vue(ordre)
        await self._marque_servi(ordre.commit, journalise=True, ordre=ordre)
        log.info(
            "version_servie",
            workspace_id=ordre.workspace_id,
            number=ordre.number,
            commit=ordre.commit,
        )
        return await self._vue(ordre)

    async def resolve_hosted_version(self) -> tuple[HostedVersionOut | None, str | None]:
        """Ce que cette stack sert, pour son propre écran et pour le diagnostic.

        Rend AUSSI le commit lu dans l'arbre, séparément de la trace en base : les deux
        peuvent diverger, et ne montrer que la trace cacherait exactement le cas qu'on
        cherche — un volume neuf sous une table qui affirme servir quelque chose.
        """
        rangee = await db_get_hosted_version(self.identity.pool)
        if rangee is None:
            return None, await self.tree.head()
        vue = HostedVersionOut(
            workspace_id=rangee.workspace_id,
            ordered_number=rangee.ordered_number,
            ordered_commit=rangee.ordered_commit,
            served_commit=rangee.served_commit,
            reason=rangee.refusal,
        )
        return vue, await self.tree.head()

    async def _amene(self, ordre: HostedVersionIn) -> str | None:
        """Va chercher le bundle chez l'enrôlement et le pose. Rend le refus, ou nul.

        Trois issues qui ne se confondent jamais : le relais refuse, le relais est
        injoignable, ou le contenu n'est pas celui qu'on a ordonné. Chacune appelle un
        geste différent chez l'administrateur de l'enrôlement, et un refus unique les
        enverrait tous chercher au même endroit.
        """
        try:
            pair = await self.identity.resolve_peer()
        except PeerMissingError:
            # Sans pair, il n'y a personne à qui demander. Ne peut arriver qu'en course
            # avec une révocation : l'ordre lui-même a été vérifié contre la clé du pair.
            return REFUSAL_NO_PEER
        corps = HostingBundleIn(
            workspace_id=ordre.workspace_id, commit=ordre.commit
        ).model_dump_json()
        try:
            reponse = await self.identity.post_signed(
                pair.contact_url,
                HOSTING_BUNDLE_PATH,
                corps.encode("utf-8"),
                http_timeout_s=HOSTING_HTTP_TIMEOUT_S,
            )
        except OriginMissingError:
            # Sans adresse publique on ne sait pas signer, et le relais refuserait — à
            # juste titre. Le dire plutôt que d'émettre pour rien.
            return REFUSAL_NO_ORIGIN
        except httpx.HTTPError as panne:
            log.warning(
                "relais_injoignable", contact_url=pair.contact_url, reason=type(panne).__name__
            )
            return REFUSAL_RELAY_UNREACHABLE
        if reponse.status_code != 200:
            log.warning(
                "relais_refuse", contact_url=pair.contact_url, status_code=reponse.status_code
            )
            return REFUSAL_RELAY_REFUSED
        paquet = reponse.content
        if len(paquet) > MAX_BUNDLE_BYTES:
            # Borné des DEUX côtés : le relais refuse de servir plus, et on refuse d'ouvrir
            # plus. Un seul des deux contrôles laisserait l'autre bout décider de ce qu'on
            # écrit sur notre volume.
            log.warning("bundle_trop_volumineux", bytes=len(paquet))
            return REFUSAL_TOO_LARGE
        try:
            await self.tree.apply(paquet, ordre.number, ordre.commit)
        except BundleRejectedError as refuse:
            return refuse.reason
        return None

    async def _marque_servi(
        self, commit: str, *, journalise: bool, ordre: HostedVersionIn | None = None
    ) -> None:
        async with self.identity.pool.acquire() as conn, conn.transaction():
            await db_record_served(conn, commit, self.identity.now())
            if journalise and ordre is not None:
                await self._write_event(conn, VERSION_SERVED_EVENT, ordre, {"commit": commit})

    async def _vue(self, ordre: HostedVersionIn) -> HostedVersionOut:
        """La réponse rendue à l'enrôlement : ce qu'on a enregistré, et ce qu'on SERT.

        `served_commit` est relu de la base après l'application, et non déduit du
        déroulement : c'est ce que l'écran d'en face affichera, et le déduire ferait
        répondre « servi » à un enregistrement qui aurait échoué.
        """
        rangee = await db_get_hosted_version(self.identity.pool)
        return HostedVersionOut(
            workspace_id=ordre.workspace_id,
            ordered_number=ordre.number,
            ordered_commit=ordre.commit,
            served_commit=None if rangee is None else rangee.served_commit,
            reason=None if rangee is None else rangee.refusal,
        )

    async def _write_event(
        self, conn: object, event_type: str, ordre: HostedVersionIn, properties: dict[str, object]
    ) -> None:
        """Écrit dans la transaction de la modification : pas de modification sans trace.

        Par `module.write_event` du socle, qui pose l'auteur SYSTÈME : l'ordre vient d'un
        autre module, par un appel signé, et personne ici n'a cliqué. Un auteur humain
        inventé ferait croire, dans un an, qu'un administrateur de cette stack a choisi
        cette version — alors que l'autorité est chez l'enrôlement, et nulle part ailleurs.
        """
        await self.identity.module.write_event(
            conn,
            event_type,
            HOSTING_OBJECT_KIND,
            ordre.workspace_id,
            {"number": ordre.number, "ordered_commit": ordre.commit, **properties},
        )
