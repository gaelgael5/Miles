from __future__ import annotations

from miles_socle.journal.api_journal import CHALLENGE, MAINTENANCE_PATH
from miles_socle.journal.published_contract import CONTRACTS_DIR, openapi_contract, rendered


def test_le_contrat_publie_suit_le_code() -> None:
    # Échoue dès que le chemin ou la forme de la réponse change sans que le contrat publié
    # suive : régénérer par `uv run miles-socle-contracts`, puis mettre l'article docflow
    # à jour. Un contrat en retard n'est pas une documentation incomplète, c'est un piège.
    for name, expected in rendered().items():
        published = (CONTRACTS_DIR / name).read_text(encoding="utf-8")
        assert published == expected, f"{name} n'est plus à jour : uv run miles-socle-contracts"


def test_le_contrat_ne_publie_QUE_la_route_d_entretien() -> None:
    """Le socle sert d'autres routes — sessions, amorçage, cultures, events — et aucune
    n'a d'appelant hors du dépôt. Les publier promettrait ce qu'on ne tient pas."""
    spec = openapi_contract()

    assert set(spec["paths"]) == {MAINTENANCE_PATH}
    assert spec["openapi"].startswith("3.1")


def test_le_refus_et_son_defi_sont_DANS_le_contrat() -> None:
    """Sans eux, le déclencheur d'hôte découvrirait le refus à 3 h 17 du matin, et son
    auteur ne saurait pas que « non configuré » et « jeton faux » rendent la même chose."""
    poste = openapi_contract()["paths"][MAINTENANCE_PATH]["post"]

    assert set(poste["responses"]) == {"200", "401"}
    refus = poste["responses"]["401"]["description"]
    assert "jeton_requis" in refus
    assert CHALLENGE in refus
    assert "non configurée" in refus


def test_le_contrat_nomme_le_secret_de_stack_et_non_une_session() -> None:
    """La route est authentifiée par un secret SYSTÈME : un lecteur du contrat qui
    chercherait un cookie de session se tromperait de bout en bout."""
    spec = openapi_contract()

    assert spec["paths"][MAINTENANCE_PATH]["post"]["security"] == [{"journalMaintenanceToken": []}]
    schema = spec["components"]["securitySchemes"]["journalMaintenanceToken"]
    assert schema == {"type": "http", "scheme": "bearer", "description": schema["description"]}
    assert "MILES_JOURNAL_MAINTENANCE_TOKEN" in schema["description"]
