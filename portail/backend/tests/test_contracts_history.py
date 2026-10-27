from __future__ import annotations

from miles.contracts.history import compare
from miles.contracts.openapi import Operation, ParsedContract


def _contract(*operations: tuple[str, str, str | None]) -> ParsedContract:
    return ParsedContract("Suivi", "3.1.0", tuple(Operation(*o) for o in operations))


V1 = _contract(("get", "/demandes", "lister"), ("delete", "/demandes/{id}", "supprimer"))
# operationId renommé sans changer l'appel, une opération retirée, une ajoutée.
V2 = _contract(("get", "/demandes", "listerDemandes"), ("post", "/demandes", "creer"))


def test_new_and_removed_operations_are_named_by_verb_and_path() -> None:
    comparison = compare((1, V1), V2)

    assert comparison.previous == 1
    assert comparison.added == frozenset({("post", "/demandes")})
    assert [(o.method, o.path) for o in comparison.removed] == [("delete", "/demandes/{id}")]


def test_first_or_unreadable_versions_compare_to_nothing() -> None:
    for previous, current in [(None, V1), ((1, None), V2), ((1, V1), None)]:
        comparison = compare(previous, current)
        assert (comparison.previous, comparison.added, comparison.removed) == (
            None,
            frozenset(),
            (),
        )
