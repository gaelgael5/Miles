"""La LECTURE d'une déclaration de chaîne, au socle depuis le 03/11/2026 (enabler b2a215ee).

Ce qui est éprouvé ici est ce qu'un CONSOMMATEUR subit : un fichier venu de git, qu'il n'a
pas écrit, et dont il doit refuser les formes qu'il ne comprend pas. Les allers-retours
écriture / lecture restent avec l'écriture, au module de paramétrage — c'est là que le
« rejeu ne fait pas de diff » se promet.
"""

from __future__ import annotations

import json

import pytest

from miles_socle.parametrage.chains import files_of, read_chain, slugs_in


def _sequence(*steps: dict[str, str], version: int = 1) -> str:
    return json.dumps({"format_version": version, "slug": "x", "label": "x", "steps": list(steps)})


@pytest.mark.parametrize(
    "text",
    [
        None,
        "pas du json",
        _sequence(version=2),
        _sequence({"name": "a", "template": "b.jslt"}),
        _sequence({"name": "../a", "template": "../a.jslt"}),
        _sequence({"name": "a", "template": "a.jslt"}, {"name": "a", "template": "a.jslt"}),
    ],
    ids=["absent", "illisible", "format", "template-detourne", "hors-repertoire", "doublon"],
)
def test_malformed_sequence_is_unreadable(text: str | None) -> None:
    assert read_chain(text) is None


def test_chains_and_their_files_are_found_in_the_tree() -> None:
    paths = [
        "transformations/comptes-import/chain.json",
        "transformations/comptes-import/normaliser.jslt",
        "transformations/colis/chain.json",
        "transformations/colis/sous/x.jslt",
        "contracts/suivi/contract.yaml",
    ]

    assert slugs_in(paths) == ["colis", "comptes-import"]
    assert files_of(paths, "comptes-import") == ["chain.json", "normaliser.jslt"]


def test_a_chain_written_before_the_models_existed_still_reads() -> None:
    """Ajout compatible : une chaîne d'avant le 24/10/2026 n'a pas ces clés."""
    text = json.dumps(
        {
            "format_version": 1,
            "slug": "import",
            "label": "Import",
            "steps": [{"name": "normaliser", "template": "normaliser.jslt", "target": None}],
        }
    )

    back = read_chain(text)

    assert back is not None
    assert back.steps[0].source_model is None and back.steps[0].destination_model is None


@pytest.mark.parametrize("value", ["pas-une-uri", "miles:/contracts/x/v1/y", 3, {}])
def test_a_model_reference_that_designates_nothing_makes_the_chain_unreadable(
    value: object,
) -> None:
    """Illisible, et non « absent » : une référence cassée ne doit pas passer pour un vide."""
    text = json.dumps(
        {
            "format_version": 1,
            "slug": "import",
            "label": "Import",
            "steps": [
                {
                    "name": "normaliser",
                    "template": "normaliser.jslt",
                    "target": None,
                    "source_model": value,
                }
            ],
        }
    )

    assert read_chain(text) is None
