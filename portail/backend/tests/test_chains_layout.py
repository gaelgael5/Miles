"""L'ÉCRITURE d'une déclaration de chaîne, et le refus d'une saisie fautive.

La lecture est au socle depuis le 03/11/2026 (enabler `b2a215ee`) et sa suite l'a suivie ;
ce qui reste ici éprouve ce que seul le module de paramétrage promet — un texte écrit à
l'identique pour une même chaîne, et un champ nommé à qui saisit. Les allers-retours
restent donc ici : ils ont besoin des deux côtés, et c'est l'écriture qui s'engage.
"""

from __future__ import annotations

import json

import pytest

from miles.chains.layout import (
    ChainDoc,
    StepDoc,
    chain_text,
    checked_steps,
    read_chain,
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


def test_a_chain_without_models_is_rewritten_byte_for_byte() -> None:
    """Les clés absentes ne s'écrivent pas : le rejeu ne fait toujours pas de diff."""
    doc = ChainDoc("import", "Import", (StepDoc("normaliser", None),))

    written = json.loads(chain_text(doc))["steps"][0]

    assert "source_model" not in written and "destination_model" not in written
