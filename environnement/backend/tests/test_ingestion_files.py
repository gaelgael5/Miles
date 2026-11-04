"""Le dépôt d'un fichier sur le disque de la stack : ses deux bornes, et ce qu'il laisse."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from environnement.ingestion.files import (
    REFUSAL_FILE_TOO_LARGE,
    REFUSAL_QUOTA_REACHED,
    DepositedFiles,
    FileRefused,
)

NAME = "a" * 32
AUTRE = "b" * 32


def _store(tmp_path: Path, *, max_bytes: int = 1_000, quota_bytes: int = 10_000) -> DepositedFiles:
    return DepositedFiles(root=tmp_path / "depots", max_bytes=max_bytes, quota_bytes=quota_bytes)


async def _chunks(*morceaux: bytes) -> AsyncIterator[bytes]:
    for morceau in morceaux:
        yield morceau


async def test_a_received_file_lands_on_disk_with_its_size_read_back(tmp_path: Path) -> None:
    store = _store(tmp_path)

    recu = await store.resolve_receive(NAME, _chunks(b'{"a": ', b"1}"))

    assert recu.size_bytes == 8
    assert store.file_path(NAME).read_bytes() == b'{"a": 1}'
    assert await store.file_used_bytes() == 8


async def test_a_file_beyond_the_declared_size_is_refused_before_being_read(
    tmp_path: Path,
) -> None:
    """Critère 19 : la borne est dans le message, sinon on ne sait pas comment découper."""
    store = _store(tmp_path, max_bytes=100)

    with pytest.raises(FileRefused) as refus:
        await store.resolve_room_for(101)

    assert (refus.value.code, refus.value.detail) == (REFUSAL_FILE_TOO_LARGE, "100")
    assert not store.root.exists()


async def test_a_deposit_that_would_exceed_the_quota_is_refused_before_being_read(
    tmp_path: Path,
) -> None:
    """Critère 18 : refusé AVANT lecture, en nommant le quota, et pas au milieu."""
    store = _store(tmp_path, quota_bytes=50)
    await store.resolve_receive(AUTRE, _chunks(b"x" * 40))

    with pytest.raises(FileRefused) as refus:
        await store.resolve_room_for(20)

    assert (refus.value.code, refus.value.detail) == (REFUSAL_QUOTA_REACHED, "50")


async def test_a_full_quota_refuses_even_an_unannounced_deposit(tmp_path: Path) -> None:
    store = _store(tmp_path, quota_bytes=40)
    await store.resolve_receive(AUTRE, _chunks(b"x" * 40))

    with pytest.raises(FileRefused) as refus:
        await store.resolve_room_for(None)

    assert refus.value.code == REFUSAL_QUOTA_REACHED


async def test_a_file_that_grows_past_its_bound_while_written_is_refused_and_removed(
    tmp_path: Path,
) -> None:
    """L'appelant n'a rien annoncé : la garde en écriture est la seule qui reste."""
    store = _store(tmp_path, max_bytes=10)

    with pytest.raises(FileRefused) as refus:
        await store.resolve_receive(NAME, _chunks(b"x" * 8, b"y" * 8))

    assert refus.value.code == REFUSAL_FILE_TOO_LARGE
    assert not store.file_path(NAME).exists()
    assert await store.file_used_bytes() == 0


async def test_a_deposit_interrupted_mid_transfer_leaves_no_partial_file(
    tmp_path: Path,
) -> None:
    """Le fichier temporaire ne fuit pas (critère 14), pas même celui d'un dépôt avorté."""
    store = _store(tmp_path)

    async def _coupe() -> AsyncIterator[bytes]:
        yield b"debut"
        raise ConnectionResetError("client parti")

    with pytest.raises(ConnectionResetError):
        await store.resolve_receive(NAME, _coupe())

    assert await store.file_names() == set()


async def test_removing_a_file_twice_is_not_an_incident(tmp_path: Path) -> None:
    """Une purge rejouée doit pouvoir repasser : c'est le régime normal d'un entretien."""
    store = _store(tmp_path)
    await store.resolve_receive(NAME, _chunks(b"{}"))

    assert await store.file_remove(NAME) is True
    assert await store.file_remove(NAME) is False


async def test_the_names_on_disk_are_listed_to_find_the_orphans(tmp_path: Path) -> None:
    store = _store(tmp_path)
    await store.resolve_receive(NAME, _chunks(b"{}"))
    await store.resolve_receive(AUTRE, _chunks(b"{}"))

    assert await store.file_names() == {NAME, AUTRE}


async def test_an_absent_directory_occupies_nothing_and_lists_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert await store.file_used_bytes() == 0
    assert await store.file_names() == set()


@pytest.mark.parametrize(
    "name",
    ["../fuite", "a" * 31, "A" * 32, "", "a" * 32 + "/x"],
    ids=["remontee", "court", "majuscules", "vide", "chemin"],
)
async def test_a_name_that_is_not_an_ingestion_identifier_is_refused(
    tmp_path: Path, name: str
) -> None:
    """Validé avant tout usage en chemin : la seule façon de sortir du répertoire est de
    ne pas regarder."""
    with pytest.raises(ValueError, match="nom de fichier"):
        _store(tmp_path).file_path(name)
