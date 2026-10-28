from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI

from miles_socle.app_state import wire_socle_services
from miles_socle.auth.admin_store import AdminAccountStore
from miles_socle.events.model import EventTypeCatalog
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.testing import admin_env, write_env

SERVICES_DU_SOCLE = (
    "health_probe",
    "auth",
    "secrets",
    "cultures",
    "preferences",
    "oidc",
    "public_url",
)


@dataclass(frozen=True)
class _Runtime:
    public_url: str | None = "https://produit.example.org"
    session_ttl_s: int = 3600
    cookie_secure: bool = True
    allow_http_identity_providers: bool = False
    db_connect_timeout_s: float = 5.0


class _Pool:
    """Le pool n'est pas touché par le câblage : les services le rangent, c'est tout."""


def _now() -> datetime:
    return datetime(2026, 10, 28, tzinfo=UTC)


def _cable(tmp_path: Path, runtime: _Runtime, *, email: str = "gael@example.org") -> FastAPI:
    env, backup = write_env(tmp_path, admin_env(email))
    app = FastAPI()
    wire_socle_services(
        app,
        settings=runtime,
        pool=cast(Any, _Pool()),
        store=AdminAccountStore.file_load(env, backup),
        cipher=SecretCipher(bytes(range(32))),
        catalog=EventTypeCatalog(frozenset()),
        http=cast(Any, httpx.AsyncClient()),
        expected_schema_version=12,
        now=_now,
    )
    return app


@pytest.mark.parametrize("service", SERVICES_DU_SOCLE)
def test_les_sept_services_du_socle_sont_poses(tmp_path: Path, service: str) -> None:
    # Nommés un par un, et non comptés : un service perdu doit faire rougir un test qui
    # dit lequel. C'est tout l'objet de ce module.
    app = _cable(tmp_path, _Runtime())

    assert hasattr(app.state, service)


def test_les_preferences_recoivent_l_instance_des_cultures(tmp_path: Path) -> None:
    # L'ordre de création n'est pas décoratif : les intervertir ne casse pas à la
    # construction, seulement à l'exécution. Ce test est ce qui tient l'ordre.
    app = _cable(tmp_path, _Runtime())

    assert app.state.preferences.cultures is app.state.cultures


def test_la_duree_de_session_passe_des_secondes_a_une_duree(tmp_path: Path) -> None:
    app = _cable(tmp_path, _Runtime(session_ttl_s=7200))

    assert app.state.auth.session_ttl == timedelta(hours=2)


@pytest.mark.parametrize("secure", [True, False])
def test_le_drapeau_du_cookie_est_celui_de_la_configuration(tmp_path: Path, secure: bool) -> None:
    # Le harnais de test le met à faux pour traverser le transport ASGI ; la production le
    # laisse à vrai. Le câblage ne doit rien décider ici.
    app = _cable(tmp_path, _Runtime(cookie_secure=secure))

    assert app.state.auth.cookie_secure is secure


@pytest.mark.parametrize("admis", [True, False])
def test_les_fournisseurs_en_http_suivent_la_configuration(tmp_path: Path, admis: bool) -> None:
    app = _cable(tmp_path, _Runtime(allow_http_identity_providers=admis))

    assert app.state.oidc.allow_http_issuer is admis


def test_l_adresse_publique_est_posee_et_donnee_a_l_oidc(tmp_path: Path) -> None:
    app = _cable(tmp_path, _Runtime(public_url="https://produit.example.org"))

    assert app.state.public_url == "https://produit.example.org"
    assert app.state.oidc.public_url == "https://produit.example.org"


def test_une_instance_sans_adresse_publique_est_un_etat_explicite(tmp_path: Path) -> None:
    # `None` posé, et non absent : une route qui construit une URL de retour doit pouvoir
    # constater qu'il n'y en a pas, au lieu de tomber sur un attribut manquant.
    app = _cable(tmp_path, _Runtime(public_url=None))

    assert app.state.public_url is None


def test_l_adresse_de_l_administrateur_est_relue_et_non_capturee(tmp_path: Path) -> None:
    """Recalculée à chaque lecture : après une réinitialisation du compte dans `.env`,
    l'ancienne adresse ne doit plus reconnaître personne."""
    env, backup = write_env(tmp_path, admin_env("avant@example.org"))
    app = FastAPI()
    store = AdminAccountStore.file_load(env, backup)
    wire_socle_services(
        app,
        settings=_Runtime(),
        pool=cast(Any, _Pool()),
        store=store,
        cipher=SecretCipher(bytes(range(32))),
        catalog=EventTypeCatalog(frozenset()),
        http=cast(Any, httpx.AsyncClient()),
        expected_schema_version=12,
        now=_now,
    )
    assert app.state.oidc.admin_email() == "avant@example.org"

    env.write_text(admin_env("apres@example.org"), encoding="utf-8")
    store = AdminAccountStore.file_load(env, backup)
    app2 = FastAPI()
    wire_socle_services(
        app2,
        settings=_Runtime(),
        pool=cast(Any, _Pool()),
        store=store,
        cipher=SecretCipher(bytes(range(32))),
        catalog=EventTypeCatalog(frozenset()),
        http=cast(Any, httpx.AsyncClient()),
        expected_schema_version=12,
        now=_now,
    )

    assert app2.state.oidc.admin_email() == "apres@example.org"


def test_l_horloge_injectee_est_celle_que_les_services_emploient(tmp_path: Path) -> None:
    # Un test qui dépend de l'heure réelle échoue un jour sur cent : l'instant s'injecte.
    app = _cable(tmp_path, _Runtime())

    assert app.state.secrets.now() == _now()
    assert app.state.cultures.now() == _now()
    assert app.state.preferences.now() == _now()
