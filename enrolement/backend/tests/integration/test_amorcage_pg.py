from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.auth.env_file import file_read_env
from miles_socle.auth.sessions import SESSION_COOKIE

from tests.integration.enrolement_stack import ADMIN_PASSWORD, open_stack

pytestmark = pytest.mark.integration

AMORCAGE = {
    "email": "gael@enrolement.invalid",
    "username": "admin",
    "password": "phrase de passe de l'amorcage",
}


async def test_l_amorcage_cree_le_premier_administrateur_puis_se_referme(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path, admin_email=None) as stack:
        visiteur = stack.anonymous()
        assert (await visiteur.get("/api/bootstrap/status")).json() == {"admin_declared": False}

        cree = await visiteur.post("/api/bootstrap", json=AMORCAGE)

        assert cree.status_code == 201
        assert (await visiteur.get("/api/bootstrap/status")).json() == {"admin_declared": True}
        # L'écran se referme DÉFINITIVEMENT : une seconde tentative est refusée, et c'est
        # la seule garde entre une installation neuve et un administrateur imposé.
        rejoue = await visiteur.post("/api/bootstrap", json=AMORCAGE)
        assert rejoue.status_code == 409
        assert rejoue.json() == {"detail": "amorcage_ferme"}
        await visiteur.aclose()


async def test_l_amorcage_ecrit_le_compte_dans_le_env_du_produit_sans_le_mot_de_passe(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path, admin_email=None) as stack:
        visiteur = stack.anonymous()
        avant = stack.env_file.read_text(encoding="utf-8")

        assert (await visiteur.post("/api/bootstrap", json=AMORCAGE)).status_code == 201

        entrees = file_read_env(stack.env_file)
        assert entrees["MILES_ADMIN_EMAIL"] == AMORCAGE["email"]
        assert entrees["MILES_ADMIN_USERNAME"] == AMORCAGE["username"]
        # Le mot de passe en clair n'entre JAMAIS dans .env, seule son empreinte.
        assert AMORCAGE["password"] not in stack.env_file.read_text(encoding="utf-8")
        assert entrees["MILES_ADMIN_PASSWORD_HASH"].startswith("$argon2id$")
        # Les entrées déjà présentes sont intactes : .env porte d'autres secrets.
        assert stack.env_file.read_text(encoding="utf-8").startswith(avant)
        await visiteur.aclose()


async def test_la_connexion_locale_pose_un_cookie_sans_domaine_parent(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        visiteur = stack.anonymous()

        ouverte = await visiteur.post(
            "/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}
        )

        assert ouverte.status_code == 200
        pose = ouverte.headers["set-cookie"]
        assert pose.startswith(f"{SESSION_COOKIE}=")
        # Étanchéité : aucun attribut Domain, donc le cookie ne vaut QUE pour cette
        # origine. Un domaine parent le rendrait lisible par les autres produits.
        assert "domain=" not in pose.lower()
        assert "httponly" in pose.lower()
        assert "samesite=lax" in pose.lower()
        await visiteur.aclose()


async def test_un_jeton_de_session_etranger_ne_vaut_rien(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        visiteur = stack.anonymous()
        visiteur.cookies.set(SESSION_COOKIE, "jeton-ouvert-sur-un-autre-produit")

        refus = await visiteur.get("/api/cultures")

        # La table des sessions est propre au produit et aucun secret de session n'est
        # partagé : un jeton valide ailleurs n'a pas d'empreinte ici.
        assert refus.status_code == 401
        assert refus.json() == {"detail": "session_requise"}
        await visiteur.aclose()


async def test_le_mot_de_passe_de_l_administrateur_du_portail_n_ouvre_rien_ici(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        visiteur = stack.anonymous()

        # Même nom d'utilisateur, mot de passe d'un autre produit : refusé. Les deux
        # comptes d'amorçage vivent dans deux .env distincts (décision du 27/10/2026).
        refus = await visiteur.post(
            "/api/auth/login", json={"username": "admin", "password": "mot de passe du portail"}
        )

        assert refus.status_code == 401
        await visiteur.aclose()


@pytest.mark.parametrize(
    "chemin", ["/api/cultures", "/api/secrets", "/api/oidc/connectors", "/api/auth/me"]
)
async def test_aucune_route_de_gestion_sans_session(
    blank_db: str, tmp_path: Path, chemin: str
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        visiteur = stack.anonymous()

        assert (await visiteur.get(chemin)).status_code == 401
        await visiteur.aclose()


async def test_la_session_de_l_administrateur_lit_son_identite(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        moi = await stack.client.get("/api/auth/me")

        assert moi.status_code == 200
        assert moi.json()["kind"] == "local_admin"
        assert moi.json()["root_admin"] is True
