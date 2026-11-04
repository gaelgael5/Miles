"""Ce que l'application rend AVANT toute session : santé et amorçage.

Les gardes de surface sont réparties par NATURE depuis le 3 novembre 2026 (enabler
`82ec7d76`) : `test_app_surface.py` pour ce qui est servi, `test_app_portillon.py` pour ce
qui est refusé, et ici ce qui répond sans que personne ne soit connecté.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_la_sante_repond_sans_session(client_sans_admin: TestClient) -> None:
    # Le script de déploiement l'interroge avant toute session, sur une installation où
    # aucun administrateur n'existe encore.
    reponse = client_sans_admin.get("/api/health")

    assert reponse.status_code == 200
    assert reponse.json() == {
        "status": "ok",
        "database": "up",
        "schema_version": 8,
        "expected_schema_version": 8,
    }


def test_l_etat_d_amorcage_est_lisible_sans_session(client_sans_admin: TestClient) -> None:
    reponse = client_sans_admin.get("/api/bootstrap/status")

    assert reponse.status_code == 200
    assert reponse.json() == {"admin_declared": False}


def test_tant_qu_aucun_administrateur_n_existe_rien_d_autre_n_est_ouvert(
    client_sans_admin: TestClient,
) -> None:
    reponse = client_sans_admin.get("/api/cultures")

    assert reponse.status_code == 403
    assert reponse.json() == {"detail": "amorcage_requis"}
