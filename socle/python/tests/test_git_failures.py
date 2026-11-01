"""La classification des échecs git, éprouvée sur de vraies sorties d'erreur de git.

Déplacé du portail avec `classify` le 01/11/2026 : un test resté chez l'ancien
propriétaire aurait laissé le socle sans garde, et le portail rouge au premier
changement de vocabulaire décidé pour le module d'enrôlement.
"""

from __future__ import annotations

import pytest

from miles_socle.git.failures import Reason, classify
from miles_socle.git.runner import GitResult


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("remote: error: GH006: Protected branch update failed", Reason.PROTECTED),
        ("! [remote rejected] x -> x (pre-receive hook declined)", Reason.PROTECTED),
        ("remote: Repository not found.", Reason.REPOSITORY_NOT_FOUND),
        ("fatal: Authentication failed for 'https://github.com/a/b.git/'", Reason.CREDENTIALS),
        ("remote: Permission to a/b.git denied to bot.", Reason.FORBIDDEN),
        ("The requested URL returned error: 403", Reason.FORBIDDEN),
        ("fatal: unable to access 'x': Could not resolve host: github.com", Reason.UNREACHABLE),
        ("The requested URL returned error: 400", Reason.FAILED),
        ("quelque chose d'imprévu", Reason.FAILED),
    ],
)
def test_git_errors_are_classified(stderr: str, reason: Reason) -> None:
    assert classify(GitResult(1, "", stderr)) is reason
