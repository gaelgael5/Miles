from __future__ import annotations

import secrets as random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from tests.integration.git_stack import (
    add_connection,
    add_secret,
    create_workspace,
    env,
    set_repository,
    wire_git,
)
from tests.integration.portal_stack import PortalStack, open_portal_stack


@dataclass
class Forge:
    portal: PortalStack
    api: httpx.AsyncClient
    url: str

    @property
    def client(self) -> httpx.AsyncClient:
        return self.portal.client

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[1].removesuffix(".git")

    async def file(self, path: str) -> str | None:
        got = await self.api.get(
            f"/api/v1/repos/miles/{self.name}/raw/{path}", params={"ref": "work/atelier"}
        )
        return got.text if got.status_code == 200 else None

    async def commits(self) -> int:
        listed = await self.api.get(
            f"/api/v1/repos/miles/{self.name}/commits",
            params={"sha": "work/atelier", "limit": 50, "stat": "false"},
        )
        return len(listed.json())


@asynccontextmanager
async def open_work_forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    """Workspace « retrait » au dépôt Gitea neuf, sa branche de travail ouverte."""
    base = env("MILES_TEST_GITEA_URL")
    headers = {"Authorization": f"token {env('MILES_TEST_GITEA_TOKEN')}"}
    async with (
        open_portal_stack(blank_db, tmp_path) as portal,
        httpx.AsyncClient(base_url=base, headers=headers) as api,
    ):
        wire_git(portal, (base.split("://", 1)[1],))
        await add_secret(portal.client, "jeton", "GIT_TOKEN", env("MILES_TEST_GITEA_TOKEN"))
        await add_connection(portal.client, "forge", base, token_secret_slug="jeton")
        name = f"cfg-{random.token_hex(4)}"
        created = await api.post("/api/v1/user/repos", json={"name": name, "private": True})
        assert created.status_code == 201
        url = f"{base}/miles/{name}.git"
        await create_workspace(portal.client)
        assert (await set_repository(portal.client, url, "forge")).status_code == 200
        opened = await portal.client.post(
            "/api/workspaces/retrait/work-branch", json={"name": "atelier"}, timeout=120
        )
        assert opened.status_code == 201, opened.text
        yield Forge(portal, api, url)
