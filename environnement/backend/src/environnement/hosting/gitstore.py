"""L'arbre que cette stack sert : où il vit, ce qu'il porte, et comment on le remplace.

**Git fait foi, et ici il fait foi deux fois.** D'abord parce que c'est l'invariant du
projet — le paramétrage d'un environnement est dans git, jamais en base. Ensuite parce que
c'est l'ARBRE, et non la table, qui dit ce qui est réellement servi : un redéploiement
remplace les images sans remplacer le volume, mais un volume neuf — première installation,
disque perdu — laisserait la table affirmer qu'on sert une version dont il ne reste rien.
`head()` interroge donc git, et c'est lui qu'on croit.

**Aucun credential n'est employé ici, et il n'en existe aucun chemin.** Ce module ne parle
jamais à la forge : il ouvre un bundle que l'enrôlement lui a servi, et `run_git` est
appelé sans `GitAccess` — aucun assistant d'identifiants n'est alors posé, et aucune
variable ne porte de jeton. C'est l'interdit central du ticket edcf78bc, et il est tenu
ici par l'absence d'argument autant que par le test d'architecture.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from miles_socle.git.runner import GitResult, run_git

# Le nom de l'étiquette, comme le portail la pose et comme l'enrôlement la sert. Importé
# du socle plutôt que réécrit : c'est la convention partagée, et une seconde écriture
# aurait divergé au premier changement fait d'un seul côté.
from miles_socle.git.versions import TAG_PREFIX

from environnement.hosting.model import (
    COMMIT_RE,
    REFUSAL_BUNDLE_UNREADABLE,
    REFUSAL_WRONG_COMMIT,
    BundleRejectedError,
)

log = structlog.get_logger(__name__)


@dataclass
class HostedTree:
    """L'arbre servi, sur le volume monté. Un geste à la fois."""

    root: Path
    # Deux ordres simultanés poseraient deux arbres dans le même répertoire. Le back-office
    # tourne en un seul processus, et ce verrou suffit à les sérialiser.
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def head(self) -> str | None:
        """Le commit RÉELLEMENT posé, lu de git. Nul si rien n'est servi.

        C'est la seule réponse en laquelle on ait le droit de croire : la table dit ce
        qu'on a fait, l'arbre dit ce qui est là. Un volume neuf rend nul alors que la
        table porte encore un commit, et c'est précisément le cas qui doit refaire le
        travail plutôt que de répondre « à jour ».
        """
        if not (self.root / ".git").is_dir():
            return None
        lu = await self._git("rev-parse", "HEAD")
        tete = lu.stdout.strip()
        return tete if lu.ok and COMMIT_RE.match(tete) else None

    async def apply(self, bundle: bytes, number: int, commit: str) -> None:
        """Ouvre le bundle, VÉRIFIE le commit ordonné, et pose l'arbre. Ou refuse.

        L'ordre des trois gestes n'est pas négociable. Le contenu arrive par une réponse
        qui n'est PAS signée — `post_signed` ne signe que l'aller — et le seul élément
        authentifié de tout l'échange est le commit, qui voyage dans l'ordre signé par
        l'enrôlement. Vérifier après avoir posé l'arbre reviendrait à servir un
        paramétrage non authentifié le temps d'une vérification, et à le laisser en place
        si le processus s'arrête entre les deux.
        """
        async with self._lock:
            await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
            if not (self.root / ".git").is_dir():
                lancé = await self._git("init", "-q")
                if not lancé.ok:
                    raise BundleRejectedError(REFUSAL_BUNDLE_UNREADABLE)
            dossier = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="miles-bundle-"))
            try:
                await self._pose(dossier, bundle, number, commit)
            finally:
                # Le bundle ne reste PAS sur le volume : il porte le paramétrage en double,
                # et un fichier oublié à chaque mise à jour remplirait le disque.
                await asyncio.to_thread(shutil.rmtree, dossier, True)

    async def _pose(self, dossier: Path, bundle: bytes, number: int, commit: str) -> None:
        paquet = dossier / "version.bundle"
        await asyncio.to_thread(paquet.write_bytes, bundle)
        ref = f"refs/tags/{TAG_PREFIX}{number}"
        # `+` : l'étiquette est écrasée si elle existe déjà, ce qui est le cas d'un ordre
        # rejoué sur un arbre partiellement posé.
        recu = await self._git("fetch", "-q", str(paquet), f"+{ref}:{ref}")
        if not recu.ok:
            # Tronqué, forgé, ou fabriqué depuis un dépôt superficiel — ce dernier cas
            # s'ouvre sur « did not send all necessary objects » (mesuré le 01/11/2026).
            log.warning("bundle_illisible", number=number, stderr=recu.stderr[:200])
            raise BundleRejectedError(REFUSAL_BUNDLE_UNREADABLE)
        lu = await self._git("rev-parse", f"{TAG_PREFIX}{number}^{{commit}}")
        porte = lu.stdout.strip()
        if not lu.ok or porte != commit:
            # LE contrôle qui fait tenir l'intégrité de l'échange. Rien n'est posé.
            log.warning("bundle_commit_inattendu", ordered=commit, carried=porte[:40])
            raise BundleRejectedError(REFUSAL_WRONG_COMMIT)
        # Tête détachée sur le commit vérifié : il n'y a pas de branche ici, et il n'en
        # faut pas — cette stack ne travaille pas le dépôt, elle en SERT un état.
        pose = await self._git("-c", "advice.detachedHead=false", "checkout", "-q", "-f", commit)
        if not pose.ok:
            log.warning("arbre_non_pose", commit=commit, stderr=pose.stderr[:200])
            raise BundleRejectedError(REFUSAL_BUNDLE_UNREADABLE)
        # Ce qu'un geste précédent aurait laissé n'a pas à survivre à celui-ci : un fichier
        # retiré par la nouvelle version resterait servi sans cela.
        await self._git("clean", "-q", "-fdx", "--exclude=.git")

    async def _git(self, *args: str) -> GitResult:
        # Sans `GitAccess`, et c'est la ligne qui matérialise l'interdit : ce module ne
        # détient aucun credential git, et n'en reçoit aucun par aucun chemin.
        return await run_git(list(args), self.root)
