from __future__ import annotations

from dataclasses import dataclass

from miles.contracts.openapi import Operation, ParsedContract


@dataclass(frozen=True)
class Comparison:
    """Ce qu'une version change par rapport à la précédente (story b2305542)."""

    # None : première version, ou précédente illisible ; rien à comparer.
    previous: int | None
    added: frozenset[tuple[str, str]]
    # Toujours exposées par la précédente : leur mapping sert encore tant que le tiers
    # expose cette version-là. Montrées, jamais invalidées.
    removed: tuple[Operation, ...]


def _key(operation: Operation) -> tuple[str, str]:
    # Verbe et chemin, pas l'operationId : un tiers le renomme sans changer l'appel.
    return operation.method, operation.path


def compare(
    previous: tuple[int, ParsedContract | None] | None, current: ParsedContract | None
) -> Comparison:
    if previous is None or current is None:
        return Comparison(None, frozenset(), ())
    number, before = previous
    if before is None:
        return Comparison(None, frozenset(), ())
    before_keys = {_key(o) for o in before.operations}
    current_keys = {_key(o) for o in current.operations}
    removed = tuple(o for o in before.operations if _key(o) not in current_keys)
    return Comparison(number, frozenset(current_keys - before_keys), removed)
