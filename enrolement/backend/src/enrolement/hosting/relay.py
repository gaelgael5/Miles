"""Le relais : servir à un environnement le contenu de la version qu'on lui a ordonnée.

C'est le relais que le ticket `edcf78bc` avait reporté, et la demande de Gael du 01/11/2026
l'a rendu nécessaire. Il existe pour une raison de sécurité et une seule : **le credential
git s'arrête ici**. L'environnement ne tire pas chez la forge, il tire chez nous. Deux
propriétés en découlent, et elles tombent toutes les deux si on les abandonne — un
environnement compromis ne livre pas l'accès au dépôt, et un environnement révoqué perd son
accès à git sans qu'on révoque quoi que ce soit chez la forge.

Fichier à part du service parce que le point de vue n'est pas le même : ailleurs on
ORDONNE, ici on SERT, et ce qui arrive ici est la demande d'un tiers dont on vérifie tout.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from miles_socle.git.failures import GitAccessError
from miles_socle.signing.hosting import HostingBundleIn

from enrolement.hosting.gitcache import file_bundle
from enrolement.hosting.model import (
    BundleRefusedError,
    RepositoryUnreadableError,
    validate_commit,
)
from enrolement.hosting.service import HostingService
from enrolement.hosting.store import db_ordered_for_peer

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HostingRelay:
    """Ce que ce module SERT du contenu d'un dépôt, et à qui exactement."""

    hosting: HostingService

    async def resolve_bundle(self, peer_base_url: str, demande: HostingBundleIn) -> bytes:
        """Le bundle de la version ordonnée à CET environnement. Fail closed, trois fois.

        La signature a déjà été vérifiée par le service d'appariement : on sait quelle
        origine appariée demande. Ça ne suffit pas, et c'est tout l'objet de cette
        méthode — être apparié donne droit à SON workspace, à la version qu'on lui a
        ordonnée, et à rien d'autre. Sans ces contrôles, un environnement légitime lirait
        le paramétrage de tous les autres.

        Les trois conditions sont vérifiées en une seule requête (`db_ordered_for_peer`)
        et non en trois lectures : l'appariement, l'environnement qu'il sert, le workspace
        qui y est placé et la version ordonnée doivent se correspondre TOUS, et une
        jointure ne peut pas en oublier un.

        Le refus est le MÊME dans les trois cas, et sans détail : l'appelant est une
        machine, et lui dire laquelle des trois conditions pèche lui apprendrait l'état de
        notre référentiel — quels workspaces existent, lesquels sont placés ailleurs.
        """
        commit = validate_commit(demande.commit)
        ordonne = await db_ordered_for_peer(self.hosting.pool, peer_base_url)
        if (
            ordonne is None
            or ordonne.workspace_id != demande.workspace_id
            or ordonne.commit != commit
        ):
            # Journalisé en NOMMANT l'écart, parce que c'est ici qu'on regardera le jour
            # où un environnement ne se met plus à jour : le refus est muet pour lui, pas
            # pour nous. L'origine est déjà vérifiée, donc sûre à écrire.
            log.warning(
                "bundle_refuse",
                peer_base_url=peer_base_url,
                asked_workspace=demande.workspace_id,
                asked_commit=commit,
                ordered_workspace=None if ordonne is None else ordonne.workspace_id,
                ordered_commit=None if ordonne is None else ordonne.commit,
            )
            raise BundleRefusedError(f"{peer_base_url} demande un contenu non ordonné")
        cible = await self.hosting.resolve_target(ordonne.environment_id)
        async with self.hosting.cache.opened(cible.workspace_id, cible.access) as git:
            # Récupéré À NOUVEAU avant de servir : le miroir est un cache, et l'étiquette
            # ordonnée peut n'y être pas encore — c'est le cas d'un module redémarré dont
            # le volume est neuf. La récupération est complète, sans quoi le bundle
            # produit s'ouvrirait chez personne (mesuré le 01/11/2026).
            versions = await self.hosting.read_versions(git, cible)
            servie = next((v for v in versions if v.commit == commit), None)
            if servie is None:
                # Le commit ordonné n'est plus porté par aucune version : supprimée à la
                # source depuis qu'on l'a ordonnée. Refus et non échec — il n'y a rien à
                # réparer ici, c'est une autre version qu'il faut choisir.
                log.warning(
                    "bundle_commit_sans_version", peer_base_url=peer_base_url, commit=commit
                )
                raise BundleRefusedError(f"aucune version ne porte {commit}")
            try:
                return await file_bundle(git, cible.repo, servie.number)
            except GitAccessError as inaccessible:
                raise RepositoryUnreadableError(inaccessible.reason.value) from inaccessible
