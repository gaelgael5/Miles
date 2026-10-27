from __future__ import annotations

import pytest

from miles.datamodels.grammar import NAME_RE
from miles.datamodels.layout import MODEL_RE


@pytest.mark.parametrize(
    "reference",
    ["pudo/import-crm", "pudo/site", "shared/compte", "shared/compte_brut", "2a/3b"],
)
def test_a_declaration_may_designate_any_model_the_screen_can_create(reference: str) -> None:
    """Le motif suit NAME_RE : une copie à la main refusait « pudo/import-crm »."""
    scope, name = reference.split("/")
    assert NAME_RE.match(scope) and NAME_RE.match(name)
    assert MODEL_RE.match(reference) is not None


@pytest.mark.parametrize("reference", ["Pudo/Site", "pudo", "a/b/c", "/site", "pudo/", ""])
def test_what_is_not_a_model_reference_is_refused(reference: str) -> None:
    assert MODEL_RE.match(reference) is None
