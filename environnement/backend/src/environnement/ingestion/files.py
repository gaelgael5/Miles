"""Les fichiers DÉPOSÉS, sur le disque de la stack : les recevoir, les retrouver, les ôter.

**Le disque est celui de la STACK**, partagé avec les autres storages de l'environnement
(amendement du 26/10/2026 au ticket `0f14adbd`). D'où le quota : un storage volumineux ne
doit pas affamer les autres, et c'est un plafond global, pas un plafond par source.

**Ce module ne décide rien d'autre que ses deux plafonds.** Ce qui est conservé, combien de
temps, et ce qui peut être purgé sans casser un import en cours est une question de la BASE
— elle seule sait ce qu'un fichier est devenu. Mélanger les deux aurait fait purger depuis
le disque un fichier dont l'import tourne encore.

**Tout est bloquant et passe par `asyncio.to_thread`** : écrire un gigaoctet depuis une
boucle d'événements la retiendrait, et c'est la boucle qui sert aussi les écrans.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import structlog

log = structlog.get_logger(__name__)

# Le nom d'un fichier déposé est l'identifiant de son ingestion : trente-deux chiffres
# hexadécimaux, engendrés par le service. VALIDÉ quand même avant tout usage en chemin —
# c'est la règle du dépôt pour toute valeur qui devient un chemin, et le jour où ce nom
# viendra d'ailleurs la garde sera déjà là.
NAME_RE = re.compile(r"^[0-9a-f]{32}$")
SUFFIX = ".json"
# Octets accumulés avant une écriture. Un aller-retour vers un fil par tronçon reçu (64
# Kio) coûterait seize mille sauts par gigaoctet pour rien ; quatre mébioctets amortissent
# le saut sans peser en mémoire, et c'est la seule valeur que ce module garde en mémoire.
FLUSH_BYTES = 4 * 1024 * 1024

# Refus de DÉPÔT propres au disque. Nommés, et distincts : l'un se corrige en découpant
# l'export, l'autre ne se corrige pas chez l'appelant du tout.
REFUSAL_FILE_TOO_LARGE = "fichier_trop_grand"
REFUSAL_QUOTA_REACHED = "quota_de_disque_atteint"


class FileRefused(Exception):
    """Le fichier ne peut pas être stocké. `code` est stable, `detail` porte la borne.

    La borne est dans le message parce que sans elle l'appelant ne sait pas s'il doit
    couper son export en deux ou en vingt (critères 18 et 19).
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}:{detail}")
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class ReceivedFile:
    """Ce qui a été posé sur le disque : son nom, et sa taille RELUE du disque.

    Relue et non comptée en chemin : un stockage normalise ce qu'on lui donne, et c'est la
    taille réelle qui sera comparée au quota la prochaine fois.
    """

    name: str
    size_bytes: int


@dataclass(frozen=True)
class DepositedFiles:
    root: Path
    # Taille maximale d'un dépôt (critère 19). Paramétrable : c'est une décision
    # d'exploitation, pas une limite technique.
    max_bytes: int
    # Quota du répertoire entier (critères 17 et 18), partagé par tous les storages.
    quota_bytes: int

    def file_path(self, name: str) -> Path:
        _checked(name)
        return self.root / f"{name}{SUFFIX}"

    async def file_used_bytes(self) -> int:
        """Ce que les fichiers déposés occupent. Un répertoire absent occupe zéro."""
        return await asyncio.to_thread(self._used_bytes)

    async def file_names(self) -> set[str]:
        """Les fichiers présents, par leur nom. Sert à retrouver les orphelins."""
        return await asyncio.to_thread(self._names)

    async def file_remove(self, name: str) -> bool:
        """Ôte le fichier. Rend faux s'il n'était plus là — un purge rejoué n'est pas un
        incident."""
        return await asyncio.to_thread(self._remove, name)

    async def resolve_room_for(self, declared: int | None) -> None:
        """Refuse AVANT lecture ce qui ne pourra pas être stocké (critères 18 et 19).

        Avant lecture, et c'est le critère : lire un gigaoctet pour le refuser à la fin
        aurait coûté le transfert et le disque. `declared` est la taille annoncée par
        l'appelant ; sans annonce, il ne reste que la garde en cours d'écriture.
        """
        if declared is not None and declared > self.max_bytes:
            raise FileRefused(REFUSAL_FILE_TOO_LARGE, str(self.max_bytes))
        libre = self.quota_bytes - await self.file_used_bytes()
        if libre <= 0 or (declared is not None and declared > libre):
            raise FileRefused(REFUSAL_QUOTA_REACHED, str(self.quota_bytes))

    async def resolve_receive(self, name: str, chunks: AsyncIterator[bytes]) -> ReceivedFile:
        """Écrit le flux reçu sous ce nom, et refuse dès que l'une des bornes est franchie.

        **Le fichier partiel est ôté avant que le refus ne remonte.** Sans cela, un dépôt
        refusé au milieu laisserait sur le disque de quoi faire refuser le suivant pour
        quota — le fichier temporaire ne doit pas fuir (critère 14), pas même celui d'un
        dépôt qui n'aboutit pas.
        """
        cible = self.file_path(name)
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        libre = self.quota_bytes - await self.file_used_bytes()
        try:
            ecrits = await self._write(cible, chunks, libre)
        except BaseException:
            # BaseException et non Exception : une annulation de tâche — client parti au
            # milieu du transfert — laisserait sinon le fichier partiel derrière elle.
            await asyncio.to_thread(self._remove, name)
            raise
        log.info("fichier_depose", nom=name, octets=ecrits)
        return ReceivedFile(name=name, size_bytes=ecrits)

    async def _write(self, cible: Path, chunks: AsyncIterator[bytes], libre: int) -> int:
        ecrits = 0
        tampon = bytearray()
        with cible.open("wb") as handle:
            async for chunk in chunks:
                tampon += chunk
                if len(tampon) < FLUSH_BYTES:
                    continue
                ecrits = await self._flush(handle, tampon, ecrits, libre)
                tampon.clear()
            if tampon:
                ecrits = await self._flush(handle, tampon, ecrits, libre)
        return ecrits

    async def _flush(self, handle: BinaryIO, tampon: bytearray, ecrits: int, libre: int) -> int:
        total = ecrits + len(tampon)
        if total > self.max_bytes:
            raise FileRefused(REFUSAL_FILE_TOO_LARGE, str(self.max_bytes))
        if total > libre:
            # Le quota est atteint PENDANT l'écriture : c'est le cas d'un appelant qui
            # n'annonce pas sa taille. Refusé en nommant le quota, jamais tronqué — un
            # document amputé serait lu comme un export incomplet du partenaire.
            raise FileRefused(REFUSAL_QUOTA_REACHED, str(self.quota_bytes))
        await asyncio.to_thread(handle.write, bytes(tampon))
        return total

    def _used_bytes(self) -> int:
        if not self.root.exists():
            return 0
        return sum(f.stat().st_size for f in self.root.glob(f"*{SUFFIX}") if f.is_file())

    def _names(self) -> set[str]:
        if not self.root.exists():
            return set()
        return {f.stem for f in self.root.glob(f"*{SUFFIX}") if f.is_file()}

    def _remove(self, name: str) -> bool:
        cible = self.file_path(name)
        if not cible.exists():
            return False
        cible.unlink()
        return True


def _checked(name: str) -> str:
    if not NAME_RE.match(name):
        # Validé avant tout usage en chemin : la seule façon qu'un nom de fichier ait de
        # sortir du répertoire est qu'on ne l'ait pas regardé.
        raise ValueError(f"nom de fichier déposé invalide : {name!r}")
    return name
