from __future__ import annotations

from environnement.published_contracts import CONTRACTS_DIR, openapi_contract, rendered


def test_le_contrat_publie_suit_le_code() -> None:
    # Échoue dès qu'une route ou une forme de réponse change sans que le contrat publié
    # suive : régénérer par `uv run miles-env-contracts`, puis mettre l'article docflow
    # à jour. Un contrat en retard n'est pas une documentation incomplète, c'est un piège.
    for name, expected in rendered().items():
        published = (CONTRACTS_DIR / name).read_text(encoding="utf-8")
        assert published == expected, f"{name} n'est plus à jour : uv run miles-env-contracts"


def test_le_contrat_ne_publie_QUE_le_point_d_entree_d_ingestion() -> None:
    """La surface d'un écran n'est pas un contrat : elle change avec lui, dans le même
    commit. Publier `/api/...` promettrait à des tiers ce qu'on ne tient pas."""
    spec = openapi_contract()

    # Deux chemins depuis le 04/11/2026 : le mode gros fichier a le sien, littéral, parce
    # que son corps, sa réponse et ses refus diffèrent. Le reste — clés d'API, storages,
    # appariement — est la surface d'un écran, et n'entre pas dans un contrat.
    assert set(spec["paths"]) == {"/ingest/{source}/{mode}", "/ingest/{source}/fichier"}
    assert spec["openapi"].startswith("3.1")


def test_les_codes_de_refus_sont_DANS_le_contrat() -> None:
    """Sans eux, un appelant découvrirait les codes en provoquant les erreurs — l'appel
    exploratoire qu'un contrat sert précisément à éviter."""
    reponses = openapi_contract()["paths"]["/ingest/{source}/{mode}"]["post"]["responses"]

    assert {"200", "201", "400", "401", "404", "409", "413", "415"} <= set(reponses)
    décrits = " ".join(r.get("description", "") for r in reponses.values())
    for code in (
        "authentification_requise",
        "corps_vide",
        "json_invalide",
        "mode_non_declare",
        "mode_ambigu",
        "mode_non_servi",
        "lot_trop_grand",
        "type_de_contenu_inattendu",
    ):
        assert code in décrits, f"le refus {code} n'est pas dans le contrat publié"


def test_la_methode_fichier_publie_sa_prise_en_charge_et_ses_refus_de_disque() -> None:
    """Le mode fichier n'accuse QUE la prise en charge : son contrat doit le dire.

    Sans cela, un appelant lirait le 202 comme un compte-rendu vide et croirait son
    document ingéré sans qu'aucun objet ne soit écrit.
    """
    chemin = openapi_contract()["paths"]["/ingest/{source}/fichier"]["post"]
    reponses = chemin["responses"]

    assert {"200", "202", "400", "401", "404", "409", "413", "415"} <= set(reponses)
    assert "prise en charge" in chemin["description"]
    décrits = " ".join(r.get("description", "") for r in reponses.values())
    for code in ("fichier_trop_grand", "quota_de_disque_atteint", "cible_non_servie"):
        assert code in décrits, f"le refus {code} n'est pas dans le contrat publié"
