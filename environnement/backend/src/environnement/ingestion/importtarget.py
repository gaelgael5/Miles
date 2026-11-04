"""Ce que la version servie offre à un import PRIS, ou le motif de son refus.

À part de l'orchestration parce que c'est une question de LECTURE : l'import a été accepté
plus tôt, contre une version et une déclaration qui ont pu changer depuis. Ce module dit si
elles sont encore là, et ce qui manque sinon — chaque motif appelant un geste différent dans
le paramétrage.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from miles_socle.transform.jpath import SplitRefusal, read_stream_split

from environnement.hosting.gitstore import HostedTree
from environnement.hosting.store import db_get_hosted_version
from environnement.ingestion.model import FILE, IngestionRefusal, Target
from environnement.ingestion.resolve import target_of
from environnement.ingestion.store_imports import ImportJob
from environnement.ingestion.writeback import NotServed, Prepared, file_prepare
from environnement.sources.declarations import file_declared_sources

# Pourquoi un import n'est plus menable. Aucun ne se devine depuis « échec ».
FAILURE_VERSION_CHANGED = "version_servie_changee"
FAILURE_NO_VERSION = "aucune_version_servie"
FAILURE_TARGET = "cible_non_servie"
FAILURE_ENTRY = "entree_non_servie"
FAILURE_SPLIT = "decoupage_non_streamable"


class NotImportable(Exception):
    """Ce que la version servie ne permet plus. Un seul type : le geste est le même."""

    def __init__(self, code: str, detail: str | None) -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Importable:
    """De quoi mener l'import sans rien relire : la cible, la table, le modèle, la chaîne,
    et les clés du tableau d'items."""

    target: Target
    prepared: Prepared
    keys: tuple[str | int, ...]


async def resolve_importable(db: Any, tree: HostedTree, job: ImportJob) -> Importable:
    """Ce que la version servie offre pour cet import, ou le motif du refus.

    **La version est comparée à celle du DÉPÔT**, et un écart refuse l'import. C'est
    délibéré : entre le dépôt et l'import, une version a pu changer le modèle du
    storage ou la chaîne, et appliquer au document un paramétrage que le déposant n'a
    jamais vu rendrait le résultat irreproductible — exactement ce que la colonne
    `version_number` existe pour empêcher. Le document est CONSERVÉ : un nouveau dépôt
    est possible, et c'est un geste explicite.
    """
    hebergee = await db_get_hosted_version(db)
    if hebergee is None:
        raise NotImportable(FAILURE_NO_VERSION, None)
    if hebergee.ordered_number != job.version_number:
        raise NotImportable(
            FAILURE_VERSION_CHANGED, f"{job.version_number} -> {hebergee.ordered_number}"
        )
    paths = await tree.file_paths()
    declarees = await file_declared_sources(tree.file_text, paths)
    try:
        cible = target_of(declarees, job.source, FILE)
    except IngestionRefusal as refus:
        # La source ou son mode ont disparu de la déclaration entre le dépôt et
        # l'import : du point de vue de l'import, le geste est le même quel que soit
        # lequel des deux — corriger le paramétrage. `detail` dit lequel.
        raise NotImportable(FAILURE_ENTRY, f"{refus.code}:{refus.detail}"[:200]) from None
    lu = read_stream_split(cible.entry.split)
    if isinstance(lu, SplitRefusal):
        # Le profil est confronté ICI AUSSI, et non seulement du côté qui édite : un
        # fichier de source vient de git, que personne ne garantit avoir été écrit par
        # un écran — une branche se modifie aussi à la main. Même fail closed que pour
        # le profil d'écriture des templates.
        raise NotImportable(FAILURE_SPLIT, f"{lu.code}:{lu.detail}"[:200]) from None
    try:
        prepared = await file_prepare(tree.file_text, paths, cible.storage, cible.entry.chain)
    except NotServed as refus:
        raise NotImportable(FAILURE_TARGET, refus.detail) from None
    return Importable(cible, prepared, lu.keys)
