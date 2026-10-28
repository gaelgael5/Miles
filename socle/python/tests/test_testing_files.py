from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.outcomes import Failed

from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.auth.env_file import file_read_env
from miles_socle.auth.passwords import verify_password
from miles_socle.secrets.crypto import SecretCipher, parse_secrets_key
from miles_socle.testing import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    BASE_ENV,
    SECRETS_KEY,
    admin_env,
    write_env,
)
from miles_socle.testing.db import DSN_ENV, blank_db_fixture, open_blank_db


def test_la_cle_d_essai_est_une_cle_que_le_produit_sait_lire() -> None:
    """La leçon du 28/10/2026, tenue ici pour les trois produits à la fois.

    La valeur en dur qui tenait cette place faisait 43 caractères, sans rembourrage :
    `parse_secrets_key` la REFUSAIT. Invisible tant qu'aucun test ne montait l'application
    entière, puisque la configuration transporte cette clé sans la lire. Ce test est ce qui
    fait qu'une valeur d'essai ne peut plus se faire passer pour une clé valide.
    """
    clef = parse_secrets_key(SECRETS_KEY)

    assert len(clef) == 32
    # Et elle chiffre réellement : une clé de la bonne longueur mais inutilisable passerait
    # le contrôle précédent.
    SecretCipher(clef)


def test_le_env_ecrit_porte_ses_deux_fichiers_en_600(tmp_path: Path) -> None:
    # Les deux, et pas seulement le premier : le backend restaure `.env` depuis `.env.bak`
    # si son écriture est interrompue, et un fichier absent le ferait échouer autrement.
    env, backup = write_env(tmp_path)

    assert env.read_text(encoding="utf-8") == BASE_ENV
    assert backup.read_text(encoding="utf-8") == ""
    assert env.stat().st_mode & 0o777 == 0o600
    assert backup.stat().st_mode & 0o777 == 0o600


def test_le_env_de_base_porte_les_temoins_que_le_produit_ne_doit_pas_ecraser() -> None:
    entrees = dict(ligne.split("=", 1) for ligne in BASE_ENV.strip().splitlines())

    assert "MILES_DB_PASSWORD" in entrees
    assert "MILES_HTTP_PORT" in entrees
    # Aucune entrée d'administrateur : c'est l'état d'une installation NEUVE, le seul où
    # l'écran d'amorçage est ouvert.
    assert not any(clef.startswith("MILES_ADMIN_") for clef in entrees)


def test_le_env_d_un_administrateur_declare_porte_les_trois_entrees(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path, admin_env("gael@example.org"))

    entrees = file_read_env(env)

    assert entrees["MILES_ADMIN_EMAIL"] == "gael@example.org"
    assert entrees["MILES_ADMIN_USERNAME"] == ADMIN_USERNAME
    # L'empreinte est calculée, jamais écrite en dur : les tests éprouvent le vrai hachage.
    assert entrees["MILES_ADMIN_PASSWORD_HASH"].startswith("$argon2id$")
    assert ADMIN_PASSWORD not in env.read_text(encoding="utf-8")
    assert backup.read_text(encoding="utf-8") == ""


def test_le_compte_declare_se_relit_par_le_socle_et_son_mot_de_passe_verifie(
    tmp_path: Path,
) -> None:
    # Le pendant du test précédent côté lecture : ce que le socle lit réellement au
    # démarrage, et non ce qu'on croit avoir écrit.
    env, backup = write_env(tmp_path, admin_env("gael@example.org"))

    store = AdminAccountStore.file_load(env, backup)

    assert store.account is not None
    assert store.account.username == ADMIN_USERNAME
    assert verify_password(store.account.password_hash.get_secret_value(), ADMIN_PASSWORD)


def test_le_env_de_base_est_conserve_quand_on_declare_un_administrateur() -> None:
    # Un produit qui écraserait le mot de passe de la base casserait la stack au
    # redémarrage : le `.env` d'essai porte ces témoins pour que le test puisse le voir.
    declare = admin_env("gael@example.org")

    assert declare.startswith(BASE_ENV)


async def test_la_base_jetable_porte_le_prefixe_du_produit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le préfixe nomme le produit : une base oubliée doit dire d'où elle vient.

    Éprouvé SANS PostgreSQL, en interceptant la connexion : c'est la raison pour laquelle
    le générateur est écrit à part de la fixture.
    """
    requetes: list[str] = []

    class _Connexion:
        async def execute(self, query: str, *args: object) -> str:
            requetes.append(query)
            return "OK"

        async def close(self) -> None:
            requetes.append("CLOSE")

    async def _connect(dsn: str) -> _Connexion:
        requetes.append(f"CONNECT {dsn}")
        return _Connexion()

    monkeypatch.setenv(DSN_ENV, "postgresql://postgres:x@db:5432/postgres")
    monkeypatch.setattr("asyncpg.connect", _connect)

    vus = [dsn async for dsn in open_blank_db("environnement_test")]

    assert len(vus) == 1
    assert "/environnement_test_" in vus[0]
    assert vus[0].startswith("postgresql://postgres:x@db:5432/")
    assert any(q.startswith('CREATE DATABASE "environnement_test_') for q in requetes)
    # Détruite à la sortie, et la connexion d'administration refermée : une base laissée
    # derrière finit par remplir la machine de test.
    assert any(q.startswith("DROP DATABASE") for q in requetes)
    assert requetes[-1] == "CLOSE"


async def test_sans_base_declaree_les_tests_d_integration_echouent_au_lieu_de_passer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pas de repli : un test d'intégration lancé sans base doit échouer, pas se déclarer
    # vert sur une doublure qu'on aurait mise là « pour que ça passe ».
    monkeypatch.delenv(DSN_ENV, raising=False)

    with pytest.raises(Failed, match=DSN_ENV):
        [dsn async for dsn in open_blank_db("essai")]


def test_la_fabrique_rend_bien_une_fixture_nommee_blank_db() -> None:
    # Le produit écrit `blank_db = blank_db_fixture("…")` : si le nom rendu n'était pas
    # celui-là, pytest ne la trouverait pas et tous ses tests d'intégration tomberaient.
    fixture = blank_db_fixture("environnement_test")

    assert "blank_db" in repr(fixture) or getattr(fixture, "name", None) == "blank_db"
