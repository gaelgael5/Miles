from __future__ import annotations

from miles.published_contracts import CONTRACTS_DIR, rendered


def test_published_contracts_match_the_code() -> None:
    # Échoue dès qu'une route ou une primitive change sans que le contrat publié suive :
    # régénérer par `uv run miles-contracts`, puis mettre l'article docflow à jour.
    for name, expected in rendered().items():
        published = (CONTRACTS_DIR / name).read_text(encoding="utf-8")
        assert published == expected, f"{name} n'est plus à jour : uv run miles-contracts"
