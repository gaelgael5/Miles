from __future__ import annotations

import secrets as random
from collections.abc import AsyncIterator
from dataclasses import dataclass
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

CONNECTIONS = "/api/git-connections"


@dataclass
class Forge:
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
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    base = env("MILES_TEST_GITEA_URL")
    write = env("MILES_TEST_GITEA_TOKEN")
    headers = {"Authorization": f"token {write}"}
    async with (
        open_portal_stack(blank_db, tmp_path) as portal,
        httpx.AsyncClient(base_url=base, headers=headers) as api,
    ):
        wire_git(portal, (base.split("://", 1)[1],))
        # Deux slugs pour le même jeton d'écriture : un remplacement de PAT qui garde
        # les droits, sans dépendre d'un second compte sur la forge.
        for slug, kind, value in (
            ("jeton", "GIT_TOKEN", write),
            ("jeton-neuf", "GIT_TOKEN", write),
            ("jeton-lecture", "GIT_TOKEN", env("MILES_TEST_GITEA_READ_TOKEN")),
            ("secret-oidc", "OIDC_CLIENT_SECRET", "s"),
        ):
            await add_secret(portal.client, slug, kind, value)
        yield Forge(portal, api, base)


async def _workspace(forge: Forge, wid: str, connection: str) -> httpx.Response:
    await create_workspace(forge.client, wid)
    return await set_repository(forge.client, await forge.repo(), connection, wid)


async def test_connection_is_declared_with_its_pat_and_replayed_without_effect(
    forge: Forge,
) -> None:
    body = {"id": "forge", "label": "Forge", "base_url": forge.base, "token_secret_slug": "jeton"}

    created = await forge.client.post(CONNECTIONS, json=body)
    replay = await forge.client.post(CONNECTIONS, json=body)

    assert created.status_code == 201, created.text
    assert created.json()["token_secret_slug"] == "jeton"
    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")


@pytest.mark.parametrize(
    "access",
    [{}, {"token_secret_slug": "absent"}, {"token_secret_slug": "secret-oidc"}],
    ids=["sans-pat", "pat-inconnu", "secret-d-un-autre-type"],
)
async def test_connection_without_a_usable_pat_is_refused_naming_it(
    forge: Forge, access: dict[str, str]
) -> None:
    body = {"id": "vide", "label": "vide", "base_url": forge.base} | access

    refused = await forge.client.post(CONNECTIONS, json=body)

    assert (refused.status_code, refused.json()["detail"]) == (422, {"field": "token_secret_slug"})
    assert (await forge.client.get(CONNECTIONS)).json() == []


async def test_certificate_is_no_longer_a_means_of_access(forge: Forge) -> None:
    body = {"id": "x", "label": "x", "base_url": forge.base, "token_secret_slug": "jeton"}

    refused = await forge.client.post(CONNECTIONS, json=body | {"certificate_id": "machine"})
    gone = await forge.client.get("/api/client-certificates")

    assert refused.status_code == 422
    assert gone.status_code == 404


async def test_connection_address_must_be_a_forge_or_an_organisation(forge: Forge) -> None:
    body = {"id": "x", "label": "x", "token_secret_slug": "jeton"}

    repo = await forge.client.post(CONNECTIONS, json=body | {"base_url": f"{forge.base}/a/b"})
    other = await forge.client.post(CONNECTIONS, json=body | {"base_url": "https://gitlab.com"})

    assert repo.json()["detail"] == {"field": "base_url"}
    assert other.json()["detail"] == {"field": "base_url"}


async def test_pat_replacement_is_tested_on_every_workspace_then_applied(forge: Forge) -> None:
    await add_connection(forge.client, "forge", forge.base, token_secret_slug="jeton")
    await _workspace(forge, "retrait", "forge")
    await _workspace(forge, "caisse", "forge")
    update = {"label": "forge", "base_url": forge.base, "verification_suffix": suffix()}

    replaced = await forge.client.put(
        f"{CONNECTIONS}/forge", json=update | {"token_secret_slug": "jeton-neuf"}, timeout=180
    )
    old_pat_freed = await forge.client.delete("/api/secrets/jeton")
    tested = await forge.portal.pool.fetchval(
        "SELECT count(*) FROM events WHERE type = 'workspace.access_checked'"
    )

    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["token_secret_slug"] == "jeton-neuf"
    assert old_pat_freed.status_code == 204
    # Deux enregistrements de dépôt, puis un essai par workspace pour le remplacement.
    assert tested == 4


async def test_connection_change_is_refused_when_a_workspace_would_lose_access(
    forge: Forge,
) -> None:
    await add_connection(forge.client, "forge", forge.base, token_secret_slug="jeton")
    await _workspace(forge, "retrait", "forge")
    update = {"label": "forge", "base_url": forge.base, "verification_suffix": suffix()}

    read_only = await forge.client.put(
        f"{CONNECTIONS}/forge", json=update | {"token_secret_slug": "jeton-lecture"}, timeout=120
    )
    moved = await forge.client.put(
        f"{CONNECTIONS}/forge",
        json=update | {"base_url": f"{forge.base}/ailleurs", "token_secret_slug": "jeton"},
    )
    relabeled = await forge.client.put(
        f"{CONNECTIONS}/forge", json=update | {"label": "Forge", "token_secret_slug": "jeton"}
    )

    detail = read_only.json()["detail"]
    assert (detail["code"], detail["workspace"], detail["right"]) == (
        "acces_insuffisant",
        "retrait",
        "creer_branche",
    )
    assert moved.json()["detail"] == {"code": "depot_hors_adresse", "workspace": "retrait"}
    assert relabeled.status_code == 200
    assert (relabeled.json()["label"], relabeled.json()["token_secret_slug"]) == ("Forge", "jeton")
