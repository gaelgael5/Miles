from __future__ import annotations

import secrets as random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tests.integration.git_stack import (
    add_connection,
    add_secret,
    create_workspace,
    env,
    set_repository,
    suffix,
    wire_git,
)
from tests.integration.portal_stack import PortalStack, open_portal_stack

pytestmark = pytest.mark.integration

CERTS = "/api/client-certificates"
CONNECTIONS = "/api/git-connections"


def _pki(name: str) -> str:
    return (Path(env("MILES_TEST_PKI")) / name).read_text()


@dataclass
class Mtls:
    portal: PortalStack
    api: httpx.AsyncClient
    base: str

    @property
    def client(self) -> httpx.AsyncClient:
        return self.portal.client

    async def repo(self) -> str:
        name = f"cfg-{random.token_hex(4)}"
        created = await self.api.post("/api/v1/user/repos", json={"name": name, "private": True})
        assert created.status_code == 201
        return f"{self.base}/miles/{name}.git"


@pytest.fixture
async def mtls(blank_db: str, tmp_path: Path) -> AsyncIterator[Mtls]:
    # Forge Gitea derrière un proxy qui exige un certificat client signé par une
    # autorité de test jetable (scripts/run-integration-tests.sh).
    base = env("MILES_TEST_MTLS_URL")
    headers = {"Authorization": f"token {env('MILES_TEST_GITEA_TOKEN')}"}
    async with (
        open_portal_stack(blank_db, tmp_path) as portal,
        httpx.AsyncClient(base_url=env("MILES_TEST_GITEA_URL"), headers=headers) as api,
    ):
        wire_git(portal, (base.split("://", 1)[1],), Path(env("MILES_TEST_PKI")) / "ca.crt")
        for slug, kind, value in (
            ("cle-client", "GIT_CLIENT_KEY", _pki("client.key")),
            ("cle-client2", "GIT_CLIENT_KEY", _pki("client2.key")),
            ("cle-etrangere", "GIT_CLIENT_KEY", _pki("foreign.key")),
            ("jeton", "GIT_TOKEN", env("MILES_TEST_GITEA_TOKEN")),
        ):
            await add_secret(portal.client, slug, kind, value)
        yield Mtls(portal, api, base)


async def _certificate(mtls: Mtls, cid: str, name: str, key: str) -> httpx.Response:
    body = {"id": cid, "label": cid, "cert_pem": _pki(f"{name}.crt"), "key_secret_slug": key}
    return await mtls.client.post(CERTS, json=body)


async def _replace(mtls: Mtls, cid: str, name: str, key: str) -> httpx.Response:
    body = {
        "label": cid,
        "cert_pem": _pki(f"{name}.crt"),
        "key_secret_slug": key,
        "verification_suffix": suffix(),
    }
    return await mtls.client.put(f"{CERTS}/{cid}", json=body, timeout=180)


async def _workspace(mtls: Mtls, wid: str, connection: str) -> httpx.Response:
    await create_workspace(mtls.client, wid)
    return await set_repository(mtls.client, await mtls.repo(), connection, wid)


async def test_certificate_is_declared_with_its_expiry(mtls: Mtls) -> None:
    created = await _certificate(mtls, "machine", "client", "cle-client")
    replay = await _certificate(mtls, "machine", "client", "cle-client")

    assert created.status_code == 201, created.text
    expiry = datetime.fromisoformat(created.json()["not_after"])
    assert timedelta(days=1) < expiry - datetime.now(UTC) <= timedelta(days=2)
    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")


@pytest.mark.parametrize(
    ("cert", "key", "expected"),
    [
        ("client", "cle-client2", {"field": "key_secret_slug", "reason": "ne_correspond_pas"}),
        ("client", "jeton", {"field": "key_secret_slug"}),
    ],
    ids=["cle-d-un-autre-certificat", "secret-d-un-autre-type"],
)
async def test_certificate_with_a_wrong_key_is_refused_naming_the_field(
    mtls: Mtls, cert: str, key: str, expected: dict[str, str]
) -> None:
    refused = await _certificate(mtls, "machine", cert, key)

    assert (refused.status_code, refused.json()["detail"]) == (422, expected)


async def test_unreadable_certificate_is_refused(mtls: Mtls) -> None:
    body = {
        "id": "machine",
        "label": "m",
        "cert_pem": "pas un PEM",
        "key_secret_slug": "cle-client",
    }

    refused = await mtls.client.post(CERTS, json=body)

    assert refused.json()["detail"] == {"field": "cert_pem", "reason": "illisible"}


async def test_certificate_alone_gives_access_through_a_connection(mtls: Mtls) -> None:
    await _certificate(mtls, "machine", "client", "cle-client")
    await add_connection(mtls.client, "mtls", mtls.base, certificate_id="machine")

    recorded = await _workspace(mtls, "retrait", "mtls")

    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["last_check"]["all_passed"] is True


@pytest.mark.parametrize("access", ["jeton-seul", "autre-autorite"])
async def test_forge_requiring_mtls_refuses_a_missing_or_foreign_certificate(
    mtls: Mtls, access: str
) -> None:
    if access == "jeton-seul":
        await add_connection(mtls.client, "mtls", mtls.base, token_secret_slug="jeton")
    else:
        await _certificate(mtls, "etranger", "foreign", "cle-etrangere")
        await add_connection(mtls.client, "mtls", mtls.base, certificate_id="etranger")

    refused = await _workspace(mtls, "retrait", "mtls")

    detail = refused.json()["detail"]
    assert (detail["code"], detail["right"], detail["reason"]) == (
        "acces_insuffisant",
        "lire",
        "certificat",
    )


async def test_connection_needs_a_token_or_a_certificate_or_both(mtls: Mtls) -> None:
    await _certificate(mtls, "machine", "client", "cle-client")
    body = {"id": "vide", "label": "vide", "base_url": mtls.base}

    neither = await mtls.client.post(CONNECTIONS, json=body)
    both = await mtls.client.post(
        CONNECTIONS, json=body | {"token_secret_slug": "jeton", "certificate_id": "machine"}
    )
    unknown = await mtls.client.post(
        CONNECTIONS, json=body | {"id": "inconnu", "certificate_id": "absent"}
    )

    assert neither.json()["detail"] == {"field": "token_secret_slug", "reason": "au_moins_un_acces"}
    assert both.status_code == 201, both.text
    assert unknown.json()["detail"] == {"field": "certificate_id"}


async def test_connection_address_must_be_a_forge_or_an_organisation(mtls: Mtls) -> None:
    body = {"id": "x", "label": "x", "token_secret_slug": "jeton"}

    repo = await mtls.client.post(CONNECTIONS, json=body | {"base_url": f"{mtls.base}/a/b"})
    other = await mtls.client.post(CONNECTIONS, json=body | {"base_url": "https://gitlab.com"})

    assert repo.json()["detail"] == {"field": "base_url"}
    assert other.json()["detail"] == {"field": "base_url"}


async def test_certificate_used_by_a_connection_cannot_be_deleted(mtls: Mtls) -> None:
    await _certificate(mtls, "machine", "client", "cle-client")
    await _certificate(mtls, "libre", "client2", "cle-client2")
    await add_connection(mtls.client, "mtls", mtls.base, certificate_id="machine")

    refused = await mtls.client.delete(f"{CERTS}/machine")
    deleted = await mtls.client.delete(f"{CERTS}/libre")
    key_freed = await mtls.client.delete("/api/secrets/cle-client2")

    assert refused.json()["detail"] == {"code": "utilise", "by": ["mtls"]}
    assert (deleted.status_code, key_freed.status_code) == (204, 204)


async def test_replacement_is_tested_on_every_workspace_then_applied(mtls: Mtls) -> None:
    await _certificate(mtls, "machine", "client", "cle-client")
    await add_connection(mtls.client, "mtls", mtls.base, certificate_id="machine")
    await _workspace(mtls, "retrait", "mtls")
    await _workspace(mtls, "caisse", "mtls")

    replaced = await _replace(mtls, "machine", "client2", "cle-client2")
    old_key_freed = await mtls.client.delete("/api/secrets/cle-client")
    tested = await mtls.portal.pool.fetchval(
        "SELECT count(*) FROM events WHERE type = 'workspace.access_checked'"
    )

    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["key_secret_slug"] == "cle-client2"
    assert old_key_freed.status_code == 204
    # Deux enregistrements de dépôt, puis un essai par workspace pour le remplacement.
    assert tested == 4


async def test_replacement_that_would_cut_one_workspace_is_refused_and_keeps_the_old(
    mtls: Mtls,
) -> None:
    created = (await _certificate(mtls, "machine", "client", "cle-client")).json()
    await add_connection(mtls.client, "mtls", mtls.base, certificate_id="machine")
    await _workspace(mtls, "retrait", "mtls")

    refused = await _replace(mtls, "machine", "foreign", "cle-etrangere")
    kept = (await mtls.client.get(CERTS)).json()[0]

    detail = refused.json()["detail"]
    assert (detail["code"], detail["workspace"], detail["reason"]) == (
        "acces_insuffisant",
        "retrait",
        "certificat",
    )
    assert (kept["key_secret_slug"], kept["not_after"]) == ("cle-client", created["not_after"])


async def test_connection_change_is_refused_when_a_workspace_would_lose_access(
    mtls: Mtls,
) -> None:
    await _certificate(mtls, "machine", "client", "cle-client")
    await add_connection(mtls.client, "mtls", mtls.base, certificate_id="machine")
    await _workspace(mtls, "retrait", "mtls")
    update = {"label": "mtls", "base_url": mtls.base, "verification_suffix": suffix()}

    token_only = await mtls.client.put(
        f"{CONNECTIONS}/mtls", json=update | {"token_secret_slug": "jeton"}, timeout=120
    )
    moved = await mtls.client.put(
        f"{CONNECTIONS}/mtls",
        json=update | {"base_url": f"{mtls.base}/ailleurs", "certificate_id": "machine"},
    )
    relabeled = await mtls.client.put(
        f"{CONNECTIONS}/mtls", json=update | {"label": "Forge mTLS", "certificate_id": "machine"}
    )

    assert token_only.json()["detail"]["workspace"] == "retrait"
    assert moved.json()["detail"] == {"code": "depot_hors_adresse", "workspace": "retrait"}
    assert relabeled.status_code == 200
    kept = relabeled.json()
    assert (kept["label"], kept["certificate_id"], kept["token_secret_slug"]) == (
        "Forge mTLS",
        "machine",
        None,
    )
