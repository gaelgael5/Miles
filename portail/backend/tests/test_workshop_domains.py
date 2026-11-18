from __future__ import annotations

import pytest

from miles.workshop import domains
from miles.workshop.domains import (
    domain_files,
    domains_in,
    reserved_scope,
    section_of,
    shared_models,
)
from miles.workshop.targeted import read_page

PATHS = [
    "domains/.gitkeep",
    "domains/suivi/models/colis.yaml",
    "domains/suivi/mappings/inbound/depot.jslt",
    "domains/suivi/mappings/outbound/etat.jslt",
    "domains/suivi/mappings/lateral/egare.jslt",
    "domains/suivi/screens/accueil.json",
    "domains/suivi/notes.txt",
    "domains/vide/.gitkeep",
    "shared/models/personne.yaml",
    "shared/models/personne.meta.yaml",
    "domains/suivi/models/colis.meta.yaml",
    "shared/models/.gitkeep",
    "shared/models/archive/vieux.yaml",
]


def test_domains_are_the_directories_under_domains_empty_ones_included() -> None:
    assert domains_in(PATHS) == ["suivi", "vide"]
    assert domains_in([]) == []


@pytest.mark.parametrize(
    ("relative", "section"),
    [
        ("models/colis.yaml", "models"),
        ("mappings/inbound/depot.jslt", "mappings/inbound"),
        ("mappings/outbound/etat.jslt", "mappings/outbound"),
        ("mappings/lateral/egare.jslt", None),
        ("models/sous/dossier.yaml", None),
        ("notes.txt", None),
        ("screens/accueil.json", "screens"),
        # L'artefact de déclaration des types d'event : UN fichier à la racine du domaine,
        # nommé d'après lui. Sans sa rubrique, il tomberait dans `misplaced` et un agent
        # conclurait que le dépôt porte un fichier égaré.
        ("suivi.wf", "event-types"),
        # Un `.wf` qui ne porte pas le nom du domaine n'est pas son artefact : le nom de
        # fichier est la clef d'`INCLUDE` du moteur, et deux homonymes s'éclipseraient.
        ("autre.wf", None),
    ],
)
def test_each_file_falls_in_its_section_or_none(relative: str, section: str | None) -> None:
    assert section_of(relative, "suivi") == section


def test_placeholders_are_never_elements() -> None:
    assert domain_files(PATHS, "vide") == []
    assert shared_models(PATHS) == ["shared/models/personne.yaml"]


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


@pytest.mark.parametrize("name", ["shared", "devices-inbound", "devices-outbound"])
def test_un_nom_de_portee_rangee_ailleurs_est_reserve(name: str) -> None:
    """Deux fichiers pour une seule identité, et c'est ce que la réserve empêche.

    `domains/devices-inbound/models/x.yaml` et `devices/inbound/x.yaml` rendent la MÊME
    portée et le MÊME nom (`entry_of`) : lequel serait écrit puis relu dépendrait de
    l'ordre de parcours des chemins. `shared` était déjà exposé à la même collision avant
    la story 31025fe6 ; il entre ici parce que c'est la même règle, pas une de plus.
    """
    assert reserved_scope(name) is True
    # La FORME reste bonne : c'est la place qui est prise, et le refus doit le dire —
    # d'où `nom_reserve` et non « champ invalide » côté service.
    assert domains.checked_domain(name) == name


@pytest.mark.parametrize("name", ["suivi", "devices", "devices-entrant", "shared-2"])
def test_un_nom_de_domaine_ordinaire_n_est_pas_reserve(name: str) -> None:
    # Discriminant : une réserve trop large interdirait des domaines légitimes, et
    # `devices` seul ne collisionne avec rien — aucune portée ne porte ce nom.
    assert reserved_scope(name) is False
