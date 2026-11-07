"""Le recouvrement de la préparation et de la copie : il a lieu, et il ne laisse rien en vol.

Sur des doublures, parce que ce qui doit être éprouvé ici est l'ORDONNANCEMENT — qui
travaille pendant que qui attend — et qu'une campagne contre PostgreSQL réel mesure des
durées sans jamais pouvoir affirmer que deux travaux se sont recouverts.

Le test central se tient par une attente croisée : la copie d'un paquet ne rend la main que
lorsque la préparation du paquet SUIVANT a démarré. Sans recouvrement elle n'aurait jamais
démarré, l'attente expire, et le test rougit. C'est la seule forme qui distingue vraiment
un recouvrement d'une séquence rapide.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest

from environnement.ingestion import fileimport
from environnement.ingestion.fileimport import FileImports, ImportLimits
from environnement.ingestion.jsonflux import DOCUMENT_INVALID, DocumentUnreadable
from environnement.ingestion.preparation import PreparedObject

LIMITS = ImportLimits(
    metadata_budget=1_000,
    apply_seconds=5.0,
    detail_cap=50,
    transform_budget=100_000,
    retention_days=1,
)
ATTENTE = 3.0


def _imports() -> FileImports:
    """Un `FileImports` réduit à ce que `_stage` touche : ses bornes."""
    return FileImports(
        pool=cast(Any, None),
        tree=cast(Any, None),
        files=cast(Any, None),
        catalog=cast(Any, None),
        now=cast(Any, None),
        limits=LIMITS,
    )


def _job() -> Any:
    return SimpleNamespace(id="ing-1")


def _entry(write_batch: int = 2) -> Any:
    return SimpleNamespace(write_batch=write_batch)


def _objet(position: int) -> PreparedObject:
    return PreparedObject(position, f"cle-{position}", {"n": position}, b"\x00" * 32)


async def _stage(imports: FileImports, chemin: Any = None) -> tuple[int, Any]:
    return await imports._stage(
        cast(Any, object()),
        _job(),
        cast(Any, object()),
        _entry(),
        cast(Any, chemin or object()),
        ("root",),
    )


@pytest.fixture(autouse=True)
def _sans_lecture(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_stage` ouvre le document : ici il n'y en a pas, les paquets sont donnés."""
    monkeypatch.setattr(fileimport, "file_iter_items", lambda chemin, keys: iter(()))


@pytest.mark.asyncio
async def test_the_next_batch_is_prepared_while_the_current_one_is_copied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La garde centrale : sans recouvrement, la copie attend indéfiniment et expire."""
    suivant_demarre = threading.Event()
    paquets: list[list[PreparedObject]] = [[_objet(0), _objet(1)], [_objet(2)], []]
    rangs: list[int] = []

    def prepare(items: Any, prepared: Any, deja: int, taille: int, limits: Any) -> Any:
        rangs.append(deja)
        if deja > 0:
            suivant_demarre.set()
        return paquets.pop(0)

    recouvert: list[bool] = []

    async def copie(conn: Any, paquet: Any) -> None:
        recouvert.append(await asyncio.to_thread(suivant_demarre.wait, ATTENTE))

    monkeypatch.setattr(fileimport, "_prepared_batch", prepare)
    monkeypatch.setattr(fileimport, "db_copy_prepared", copie)

    lus, incident = await _stage(_imports())

    assert (lus, incident) == (3, None)
    # La PREMIÈRE copie a vu la préparation suivante démarrer : c'est le recouvrement.
    assert recouvert[0] is True, "la copie n'a pas été recouverte par la préparation suivante"
    # Et les rangs restent ceux du document, dans l'ordre : le recouvrement ne doit pas
    # faire préparer deux fois le même, ni sauter un rang de départ.
    assert rangs == [0, 2, 3]


@pytest.mark.asyncio
async def test_only_one_preparation_runs_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'itérateur du document n'est pas réentrant : deux fils y puisant entremêleraient
    les items sans que rien ne le signale."""
    en_cours = 0
    maximum = 0
    verrou = threading.Lock()
    paquets: list[list[PreparedObject]] = [[_objet(rang)] for rang in range(6)] + [[]]

    def prepare(items: Any, prepared: Any, deja: int, taille: int, limits: Any) -> Any:
        nonlocal en_cours, maximum
        with verrou:
            en_cours += 1
            maximum = max(maximum, en_cours)
        try:
            return paquets.pop(0)
        finally:
            with verrou:
                en_cours -= 1

    async def copie(conn: Any, paquet: Any) -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(fileimport, "_prepared_batch", prepare)
    monkeypatch.setattr(fileimport, "db_copy_prepared", copie)

    lus, incident = await _stage(_imports())

    assert (lus, incident) == (6, None)
    assert maximum == 1


@pytest.mark.asyncio
async def test_an_unreadable_document_still_reports_the_items_read_before_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Critères 7 et 8 : le recouvrement ne change pas ce qui a été rangé avant l'incident."""
    paquets: list[list[PreparedObject]] = [[_objet(0), _objet(1)]]
    copies: list[int] = []

    def prepare(items: Any, prepared: Any, deja: int, taille: int, limits: Any) -> Any:
        if not paquets:
            raise DocumentUnreadable(DOCUMENT_INVALID, "tableau non ferme")
        return paquets.pop(0)

    async def copie(conn: Any, paquet: Any) -> None:
        copies.append(len(paquet))

    monkeypatch.setattr(fileimport, "_prepared_batch", prepare)
    monkeypatch.setattr(fileimport, "db_copy_prepared", copie)

    lus, incident = await _stage(_imports())

    assert (lus, incident) == (2, (DOCUMENT_INVALID, "tableau non ferme"))
    assert copies == [2]


@pytest.mark.asyncio
async def test_a_failing_copy_waits_for_the_preparation_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une préparation en vol tourne dans un FIL : on ne l'interrompt pas, on l'attend.

    La laisser partir ferait puiser un fil dans l'itérateur d'un import abandonné, et
    asyncio signalerait une tâche détruite en vol — un bruit qui masque la vraie cause.
    """
    terminee = threading.Event()
    paquets: list[list[PreparedObject]] = [[_objet(0)], [_objet(1)], []]

    def prepare(items: Any, prepared: Any, deja: int, taille: int, limits: Any) -> Any:
        paquet = paquets.pop(0)
        if deja > 0:
            terminee.set()
        return paquet

    async def copie(conn: Any, paquet: Any) -> None:
        raise RuntimeError("la base a lâché")

    monkeypatch.setattr(fileimport, "_prepared_batch", prepare)
    monkeypatch.setattr(fileimport, "db_copy_prepared", copie)

    with pytest.raises(RuntimeError, match="la base a lâché"):
        await _stage(_imports())

    assert terminee.is_set(), "la préparation en vol n'a pas été attendue"
    assert not [tache for tache in asyncio.all_tasks() if tache is not asyncio.current_task()]
