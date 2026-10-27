from __future__ import annotations

import json

import pytest

from miles.chains.layout import (
    ChainDoc,
    StepDoc,
    chain_text,
    checked_steps,
    files_of,
    read_chain,
    slugs_in,
)
from miles.workspaces.model import WorkspaceInputError

DOC = ChainDoc(
    "comptes-import",
    "Import des comptes : « nettoyage » # v1",
    (StepDoc("normaliser", None), StepDoc("enrichir", "$.client.adresse")),
)


def test_sequence_is_written_in_order_and_reads_back_unchanged() -> None:
    text = chain_text(DOC)

    assert read_chain(text) == DOC
    assert chain_text(DOC) == text
    assert '"template": "normaliser.jslt"' in text
    assert text.index("normaliser") < text.index("enrichir")


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


@pytest.mark.parametrize("names", [["a", "a"], ["A"], ["../x"], ["un/deux"]])
def test_step_names_become_file_names_so_they_are_checked(names: list[str]) -> None:
    with pytest.raises(WorkspaceInputError) as caught:
        checked_steps([StepDoc(n, None) for n in names])

    assert (caught.value.field, caught.value.reason) == ("steps", "nom_d_etape")


def test_a_step_carries_the_models_it_reads_and_produces() -> None:
    doc = ChainDoc(
        "import",
        "Import",
        (StepDoc("normaliser", None, "miles:/shared/brut", "miles:/domains/pudo/compte"),),
    )

    back = read_chain(chain_text(doc))

    assert back == doc
    written = json.loads(chain_text(doc))["steps"][0]
    assert written["source_model"] == "miles:/shared/brut"
    assert written["destination_model"] == "miles:/domains/pudo/compte"


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


def test_a_chain_without_models_is_rewritten_byte_for_byte() -> None:
    """Les clés absentes ne s'écrivent pas : le rejeu ne fait toujours pas de diff."""
    doc = ChainDoc("import", "Import", (StepDoc("normaliser", None),))

    written = json.loads(chain_text(doc))["steps"][0]

    assert "source_model" not in written and "destination_model" not in written


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
