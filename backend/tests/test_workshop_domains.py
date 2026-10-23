from __future__ import annotations

import pytest

from miles.workshop import domains
from miles.workshop.domains import domain_files, domains_in, section_of, shared_messages
from miles.workshop.targeted import read_page

PATHS = [
    "domains/.gitkeep",
    "domains/suivi/messages/colis.yaml",
    "domains/suivi/mappings/inbound/depot.jslt",
    "domains/suivi/mappings/outbound/etat.jslt",
    "domains/suivi/mappings/lateral/egare.jslt",
    "domains/suivi/screens/accueil.json",
    "domains/suivi/notes.txt",
    "domains/vide/.gitkeep",
    "shared/messages/personne.yaml",
    "shared/messages/personne.meta.yaml",
    "domains/suivi/messages/colis.meta.yaml",
    "shared/messages/.gitkeep",
    "shared/messages/archive/vieux.yaml",
]


def test_domains_are_the_directories_under_domains_empty_ones_included() -> None:
    assert domains_in(PATHS) == ["suivi", "vide"]
    assert domains_in([]) == []


@pytest.mark.parametrize(
    ("relative", "section"),
    [
        ("messages/colis.yaml", "messages"),
        ("mappings/inbound/depot.jslt", "mappings/inbound"),
        ("mappings/outbound/etat.jslt", "mappings/outbound"),
        ("mappings/lateral/egare.jslt", None),
        ("messages/sous/dossier.yaml", None),
        ("notes.txt", None),
        ("screens/accueil.json", "screens"),
    ],
)
def test_each_file_falls_in_its_section_or_none(relative: str, section: str | None) -> None:
    assert section_of(relative) == section


def test_placeholders_are_never_elements() -> None:
    assert domain_files(PATHS, "vide") == []
    assert shared_messages(PATHS) == ["shared/messages/personne.yaml"]


async def _read(path: str) -> str:
    return "x" * 10


async def test_a_page_stops_at_the_bound_and_says_where_to_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(domains, "MAX_CONTENT_BYTES", 25)
    monkeypatch.setattr("miles.workshop.targeted.MAX_CONTENT_BYTES", 25)
    paths = ["a", "b", "c", "d", "e"]

    first = await read_page(_read, paths, None)
    second = await read_page(_read, paths, first.next_after)

    assert [(e.path, e.content is not None) for e in first.elements] == [
        ("a", True),
        ("b", True),
        ("c", True),
        ("d", False),
        ("e", False),
    ]
    assert (first.truncated, first.next_after) == (True, "c")
    assert [e.path for e in second.elements] == ["d", "e"]
    assert (second.truncated, second.next_after) == (False, None)


async def test_one_oversized_element_is_still_returned_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("miles.workshop.targeted.MAX_CONTENT_BYTES", 5)

    page = await read_page(_read, ["a", "b"], None)

    assert [e.content for e in page.elements] == ["x" * 10, None]
    assert page.next_after == "a"
