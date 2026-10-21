from __future__ import annotations

import os
import secrets as random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from miles.events.model import EventTypeCatalog
from miles.secrets.crypto import SecretCipher
from miles.secrets.service import EVENT_TYPES as SECRET_EVENTS
from miles.secrets.service import SecretsService
from miles.workspaces.model import EVENT_TYPES as WORKSPACE_EVENTS
from miles.workspaces.service import WorkspacesService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces"


def _env(name: str) -> str:
    # Posés par scripts/run-integration-tests.sh : forge Gitea derrière un proxy qui
    # exige un certificat client signé par une autorité de test jetable.
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} absent : lancer via scripts/run-integration-tests.sh")
    return value


def _pki(name: str) -> str:
    return (Path(_env("MILES_TEST_PKI")) / name).read_text()


@dataclass
class Mtls:
    portal: PortalStack
    api: httpx.AsyncClient

    async def repo(self) -> str:
        name = f"cfg-{random.token_hex(4)}"
        created = await self.api.post("/api/v1/user/repos", json={"name": name, "private": True})
        assert created.status_code == 201
        return f"{_env('MILES_TEST_MTLS_URL')}/miles/{name}.git"


@pytest.fixture
async def mtls(blank_db: str, tmp_path: Path) -> AsyncIterator[Mtls]:
    catalog = EventTypeCatalog(SECRET_EVENTS | WORKSPACE_EVENTS)
    headers = {"Authorization": f"token {_env('MILES_TEST_GITEA_TOKEN')}"}
    host = _env("MILES_TEST_MTLS_URL").split("://", 1)[1]
    async with (
        open_portal_stack(blank_db, tmp_path) as portal,
        httpx.AsyncClient(base_url=_env("MILES_TEST_GITEA_URL"), headers=headers) as api,
    ):
        secrets = SecretsService(portal.pool, SecretCipher(os.urandom(32)), catalog, utc_now)
        portal.app.state.secrets = secrets
        portal.app.state.workspaces = WorkspacesService(
            portal.pool, secrets, catalog, utc_now, (host,), Path(_env("MILES_TEST_PKI")) / "ca.crt"
        )
        for slug, kind, value in (
            ("cle-client", "GIT_CLIENT_KEY", _pki("client.key")),
            ("cle-client2", "GIT_CLIENT_KEY", _pki("client2.key")),
            ("cle-etrangere", "GIT_CLIENT_KEY", _pki("foreign.key")),
            ("jeton", "GIT_TOKEN", _env("MILES_TEST_GITEA_TOKEN")),
        ):
            body = {"slug": slug, "label": slug, "secret_type": kind, "value": value}
            assert (await portal.client.post("/api/secrets", json=body)).status_code == 201
        yield Mtls(portal, api)


def _cert(name: str, key: str) -> dict[str, str]:
    return {"cert_pem": _pki(f"{name}.crt"), "key_secret_slug": key}


async def _create(mtls: Mtls, url: str, **fields: object) -> httpx.Response:
    body = {
        "id": "retrait",
        "name": "Retrait",
        "repo_url": url,
        "verification_suffix": random.token_hex(4),
    } | fields
    return await mtls.portal.client.post(ROUTE, json=body, timeout=120)


async def test_certificate_alone_gives_access_and_its_expiry_is_shown(mtls: Mtls) -> None:
    created = await _create(
        mtls, await mtls.repo(), client_certificate=_cert("client", "cle-client")
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["git_secret_slug"] is None
    expiry = datetime.fromisoformat(body["client_cert_not_after"])
    assert timedelta(days=1) < expiry - datetime.now(UTC) <= timedelta(days=2)


async def test_token_and_certificate_together_are_accepted(mtls: Mtls) -> None:
    created = await _create(
        mtls,
        await mtls.repo(),
        git_secret_slug="jeton",
        client_certificate=_cert("client", "cle-client"),
    )

    assert created.status_code == 201


@pytest.mark.parametrize(
    "certificate", [None, "foreign"], ids=["jeton-sans-certificat", "autre-autorite"]
)
async def test_forge_requiring_mtls_refuses_a_missing_or_foreign_certificate(
    mtls: Mtls, certificate: str | None
) -> None:
    # Construits ici, pas à la collecte : la PKI n'existe que sous le script d'intégration.
    fields: dict[str, object] = (
        {"git_secret_slug": "jeton"}
        if certificate is None
        else {"client_certificate": _cert(certificate, "cle-etrangere")}
    )
    refused = await _create(mtls, await mtls.repo(), **fields)

    detail = refused.json()["detail"]
    assert (detail["code"], detail["right"], detail["reason"]) == (
        "acces_insuffisant",
        "lire",
        "certificat",
    )


async def test_key_that_does_not_match_the_certificate_is_refused_before_any_attempt(
    mtls: Mtls,
) -> None:
    refused = await _create(
        mtls, await mtls.repo(), client_certificate=_cert("client", "cle-client2")
    )

    assert refused.json()["detail"] == {
        "field": "client_key_secret_slug",
        "reason": "ne_correspond_pas",
    }
    checked = "SELECT count(*) FROM events WHERE type = 'workspace.access_checked'"
    assert await mtls.portal.pool.fetchval(checked) == 0


async def test_neither_token_nor_certificate_is_refused(mtls: Mtls) -> None:
    refused = await _create(mtls, await mtls.repo())

    assert refused.json()["detail"] == {"field": "git_secret_slug", "reason": "au_moins_un_acces"}


async def test_certificate_is_replaced_without_recreating_the_workspace(mtls: Mtls) -> None:
    await _create(mtls, await mtls.repo(), client_certificate=_cert("client", "cle-client"))

    replaced = await mtls.portal.client.put(
        f"{ROUTE}/retrait/client-certificate",
        json={**_cert("client2", "cle-client2"), "verification_suffix": random.token_hex(4)},
        timeout=120,
    )
    old_key_freed = await mtls.portal.client.delete("/api/secrets/cle-client")
    new_key_held = await mtls.portal.client.delete("/api/secrets/cle-client2")

    assert replaced.status_code == 200, replaced.text
    expiry = datetime.fromisoformat(replaced.json()["client_cert_not_after"])
    assert expiry - datetime.now(UTC) <= timedelta(days=1)
    assert replaced.json()["client_key_secret_slug"] == "cle-client2"
    assert old_key_freed.status_code == 204
    assert new_key_held.status_code == 409


async def test_replacement_that_would_cut_access_is_refused_and_keeps_the_old_one(
    mtls: Mtls,
) -> None:
    created = (
        await _create(mtls, await mtls.repo(), client_certificate=_cert("client", "cle-client"))
    ).json()

    refused = await mtls.portal.client.put(
        f"{ROUTE}/retrait/client-certificate",
        json={**_cert("foreign", "cle-etrangere"), "verification_suffix": random.token_hex(4)},
        timeout=120,
    )
    kept = (await mtls.portal.client.get(f"{ROUTE}/retrait")).json()

    assert refused.json()["detail"]["code"] == "acces_insuffisant"
    assert kept["client_cert_not_after"] == created["client_cert_not_after"]
    assert kept["client_key_secret_slug"] == "cle-client"
