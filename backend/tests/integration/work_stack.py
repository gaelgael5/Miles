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

# La racine est en lecture seule (story dca0eb0e) : on modifie dans une branche enfant.
ROOT = "atelier"
EDITION = "edition"
EDITED = f"back/retrait/{EDITION}"


@dataclass
class Forge:
    portal: PortalStack
    api: httpx.AsyncClient
    url: str
    # Branche git que lisent `file` et `commits` par défaut : celle où le client écrit.
    edited: str = EDITED
    # Le client (l'administrateur) a-t-il la main sur `edition` ? Ses modifications y
    # restent alors locales jusqu'à publication (story 9def0adc).
    held: bool = False

    @property
    def client(self) -> httpx.AsyncClient:
        return self.portal.client

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[1].removesuffix(".git")

    async def publish(self) -> None:
        """Publie les commits locaux de la prise de main, comme le bouton « Publier »."""
        published = await self.client.post(
            f"/api/workspaces/retrait/branches/{EDITION}/hold/publish", timeout=120
        )
        assert published.status_code == 200, published.text

    async def identity(self) -> str:
        """« Nom <e-mail> » du compte de forge de l'administrateur, comme Miles l'a lu."""
        me = (await self.api.get("/api/v1/user")).json()
        return f"{me.get('full_name') or me['login']} <{me['email']}>"

    async def file(self, path: str, ref: str | None = None) -> str | None:
        """Le fichier tel que la forge le montre, une fois publié ce que le client a modifié.

        Les tests d'écriture regardent ce qui sortira de Miles : publier d'abord est voulu.
        `remote_file` lit la forge sans rien publier.
        """
        if self.held and ref is None:
            await self.publish()
        return await self.remote_file(path, ref)

    async def remote_file(self, path: str, ref: str | None = None) -> str | None:
        ref = ref or self.edited
        got = await self.api.get(f"/api/v1/repos/miles/{self.name}/raw/{path}", params={"ref": ref})
        return got.text if got.status_code == 200 else None

    async def commits(self, ref: str | None = None) -> int:
        if self.held and ref is None:
            await self.publish()
        ref = ref or self.edited
        listed = await self.api.get(
            f"/api/v1/repos/miles/{self.name}/commits",
            params={"sha": ref, "limit": 50, "stat": "false"},
        )
        return len(listed.json())


async def register_identity(client: httpx.AsyncClient) -> None:
    """PAT personnel de l'administrateur pour la connexion « forge » (story 033e5ff3)."""
    registered = await client.put(
        "/api/auth/me/git-identities/forge",
        json={"token": env("MILES_TEST_GITEA_TOKEN")},
        timeout=60,
    )
    assert registered.status_code == 200, registered.text


async def take_hold(client: httpx.AsyncClient, slug: str = EDITION) -> httpx.Response:
    return await client.post(f"/api/workspaces/retrait/branches/{slug}/hold", timeout=120)


@asynccontextmanager
async def open_work_forge(
    blank_db: str, tmp_path: Path, *, edition: bool = True, hold: bool = True
) -> AsyncIterator[Forge]:
    """Workspace « retrait » au dépôt Gitea neuf, sa racine et une branche enfant ouvertes.

    Le client vise la branche enfant par défaut (`?branch=edition`), puisque la racine
    refuse toute modification ; un test qui parle de la racine la désigne explicitement
    (`params={"branch": ROOT}`), le paramètre de la requête l'emportant. `edition=False` :
    la racine seule, sans branche par défaut, pour les tests des branches elles-mêmes.
    `hold` : l'administrateur prend la main sur la branche enfant (story 9def0adc), sans
    quoi rien ne s'y modifie ; `hold=False` pour les tests de la prise de main elle-même.
    """
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
        if not edition:
            yield Forge(portal, api, url, f"back/retrait/{ROOT}")
            return
        child = await portal.client.post(
            "/api/workspaces/retrait/branches",
            json={"label": "Édition", "slug": EDITION},
            timeout=120,
        )
        assert child.status_code == 201, child.text
        portal.client.params = httpx.QueryParams({"branch": EDITION})
        forge = Forge(portal, api, url)
        if hold:
            await register_identity(portal.client)
            taken = await take_hold(portal.client)
            assert taken.status_code == 201, taken.text
            forge.held = True
        yield forge
