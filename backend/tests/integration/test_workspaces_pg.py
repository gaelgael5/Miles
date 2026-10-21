from __future__ import annotations

import os
import secrets as random
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from miles.events.model import EventTypeCatalog
from miles.secrets.crypto import SecretCipher
from miles.secrets.service import EVENT_TYPES as SECRET_EVENTS
from miles.secrets.service import SecretsService
from miles.workspaces.service import EVENT_TYPES as WORKSPACE_EVENTS
from miles.workspaces.service import WorkspacesService
from tests.integration.portal_stack import PortalStack, open_portal_stack, utc_now

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces"


def _env(name: str) -> str:
    # Posés par scripts/run-integration-tests.sh, qui lance une forge Gitea jetable :
    # les cinq droits s'éprouvent par de vrais push, sur de vrais dépôts privés.
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} absent : lancer via scripts/run-integration-tests.sh")
    return value


@dataclass
class Forge:
    portal: PortalStack
    api: httpx.AsyncClient
    base: str

    async def repo(self, *, auto_init: bool = False) -> str:
        name = f"cfg-{random.token_hex(4)}"
        created = await self.api.post(
            "/api/v1/user/repos", json={"name": name, "private": True, "auto_init": auto_init}
        )
        assert created.status_code == 201, created.text
        return f"{self.base}/miles/{name}.git"

    async def branches(self, url: str) -> list[str]:
        name = url.rsplit("/", 1)[1].removesuffix(".git")
        listed = await self.api.get(f"/api/v1/repos/miles/{name}/branches")
        return [b["name"] for b in listed.json()]

    async def tags(self, url: str) -> list[str]:
        name = url.rsplit("/", 1)[1].removesuffix(".git")
        return [t["name"] for t in (await self.api.get(f"/api/v1/repos/miles/{name}/tags")).json()]


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    base = _env("MILES_TEST_GITEA_URL")
    host = base.split("://", 1)[1]
    catalog = EventTypeCatalog(SECRET_EVENTS | WORKSPACE_EVENTS)
    headers = {"Authorization": f"token {_env('MILES_TEST_GITEA_TOKEN')}"}
    async with (
        open_portal_stack(blank_db, tmp_path) as portal,
        httpx.AsyncClient(base_url=base, headers=headers) as api,
    ):
        secrets = SecretsService(portal.pool, SecretCipher(os.urandom(32)), catalog, utc_now)
        portal.app.state.secrets = secrets
        portal.app.state.workspaces = WorkspacesService(
            portal.pool, secrets, catalog, utc_now, (host,)
        )
        for slug, value in (
            ("git-ecriture", _env("MILES_TEST_GITEA_TOKEN")),
            ("git-lecture", _env("MILES_TEST_GITEA_READ_TOKEN")),
            ("git-faux", "jeton-invalide"),
        ):
            body = {"slug": slug, "label": slug, "secret_type": "GIT_TOKEN", "value": value}
            assert (await portal.client.post("/api/secrets", json=body)).status_code == 201
        yield Forge(portal, api, base)


def _body(url: str, **overrides: object) -> dict[str, object]:
    return {
        "id": "retrait",
        "name": "Retrait de colis",
        "repo_url": url,
        "git_secret_slug": "git-ecriture",
        "verification_suffix": random.token_hex(4),
    } | overrides


async def _create(forge: Forge, url: str, **overrides: object) -> httpx.Response:
    return await forge.portal.client.post(ROUTE, json=_body(url, **overrides), timeout=120)


async def test_empty_repository_gets_main_then_passes_the_five_rights(forge: Forge) -> None:
    url = await forge.repo()

    created = await _create(forge, url)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["last_check"]["all_passed"] is True
    assert [c["right"] for c in body["last_check"]["checks"]] == [
        "lire",
        "creer_branche",
        "pousser",
        "poser_tag",
        "supprimer_branche",
    ]
    assert body["security_service_id"] is None
    assert body["last_check"]["initialized_branch"] == "main"
    assert await forge.branches(url) == ["main"] and await forge.tags(url) == []


async def test_repository_with_content_is_accepted_and_counted(forge: Forge) -> None:
    url = await forge.repo(auto_init=True)

    created = await _create(forge, url)

    assert created.status_code == 201
    assert created.json()["last_check"]["existing_branches"] == 1
    assert await forge.branches(url) == ["main"]


async def test_replaying_the_creation_creates_nothing_and_says_so(forge: Forge) -> None:
    url = await forge.repo()
    await _create(forge, url)

    again = await _create(forge, url)

    assert again.status_code == 200
    assert again.headers["x-miles-already-exists"] == "true"
    assert await forge.portal.pool.fetchval("SELECT count(*) FROM workspaces") == 1


async def test_same_repository_cannot_serve_two_workspaces(forge: Forge) -> None:
    url = await forge.repo()
    await _create(forge, url)

    other = await _create(forge, url.replace("/miles/", "/MILES/"), id="depot")
    taken = await _create(forge, await forge.repo())

    assert (other.status_code, other.json()["detail"]) == (409, "depot_deja_associe")
    assert (taken.status_code, taken.json()["detail"]) == (409, "identifiant_pris")


@pytest.mark.parametrize(
    ("secret", "right", "reason"),
    [
        ("git-faux", "lire", "identifiants"),
        ("git-lecture", "creer_branche", "droit_refuse"),
    ],
)
async def test_insufficient_access_is_refused_naming_the_right(
    forge: Forge, secret: str, right: str, reason: str
) -> None:
    refused = await _create(forge, await forge.repo(), git_secret_slug=secret)

    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert (detail["code"], detail["right"], detail["reason"]) == (
        "acces_insuffisant",
        right,
        reason,
    )
    assert await forge.portal.pool.fetchval("SELECT count(*) FROM workspaces") == 0


async def test_missing_repository_is_named(forge: Forge) -> None:
    refused = await _create(forge, f"{forge.base}/miles/absent-{random.token_hex(3)}.git")

    assert refused.json()["detail"]["reason"] == "depot_inexistant"


async def test_protection_on_the_verification_pattern_is_explained(forge: Forge) -> None:
    url = await forge.repo(auto_init=True)
    name = url.rsplit("/", 1)[1].removesuffix(".git")
    protection = {"rule_name": "miles-verification-*", "enable_push": False}
    protected = await forge.api.post(
        f"/api/v1/repos/miles/{name}/branch_protections", json=protection
    )
    assert protected.status_code == 201

    refused = await _create(forge, url)

    detail = refused.json()["detail"]
    assert (detail["right"], detail["reason"]) == ("creer_branche", "protection")
    # La branche n'a pas pu être créée, donc rien ne reste à nettoyer.
    assert detail["report"]["residual_branch"] in (None, detail["report"]["branch"])


async def test_no_secret_is_refused_before_any_attempt(forge: Forge) -> None:
    refused = await _create(forge, await forge.repo(), git_secret_slug=None)

    assert (refused.status_code, refused.json()["detail"]) == (422, {"field": "git_secret_slug"})
    assert (
        await forge.portal.pool.fetchval(
            "SELECT count(*) FROM events WHERE type LIKE 'workspace.%'"
        )
        == 0
    )


async def test_unknown_security_service_reference_is_refused(forge: Forge) -> None:
    refused = await _create(forge, await forge.repo(), security_service_id="absent")

    assert refused.json()["detail"] == {"field": "security_service_id"}


async def test_access_can_be_rechecked_from_the_workspace_and_is_journaled(forge: Forge) -> None:
    url = await forge.repo()
    await _create(forge, url)

    report = await forge.portal.client.post(
        f"{ROUTE}/retrait/access-check", json={"verification_suffix": "0badc0de"}, timeout=120
    )
    rows = await forge.portal.pool.fetch(
        "SELECT e.type, e.author_subject, e.properties->>'all_passed' AS ok FROM events e"
        " JOIN event_objects o ON o.event_id = e.id WHERE o.object_kind = 'workspace'"
        " ORDER BY o.sequence"
    )

    assert report.json()["branch"] == "miles-verification-0badc0de"
    assert report.json()["all_passed"] is True
    assert [(r["type"], r["author_subject"]) for r in rows] == [
        ("workspace.access_checked", "admin"),
        ("workspace.created", "admin"),
        ("workspace.access_checked", "admin"),
    ]


async def test_git_secret_in_use_by_a_workspace_cannot_be_deleted(forge: Forge) -> None:
    await _create(forge, await forge.repo())

    refused = await forge.portal.client.delete("/api/secrets/git-ecriture")

    assert refused.json()["detail"]["consumers"] == [{"kind": "workspace", "id": "retrait"}]


async def _open(forge: Forge, name: str = "atelier") -> httpx.Response:
    return await forge.portal.client.post(
        f"{ROUTE}/retrait/work-branch", json={"name": name}, timeout=120
    )


async def test_fresh_workspace_has_no_work_branch_until_one_is_opened(forge: Forge) -> None:
    url = await forge.repo()
    created = (await _create(forge, url)).json()

    opened = await _open(forge)

    assert created["work_branch"] is None
    assert opened.status_code == 201
    assert (opened.json()["outcome"], opened.json()["workspace"]["work_branch"]) == (
        "initialisee",
        "work/atelier",
    )
    assert set(await forge.branches(url)) == {"main", "work/atelier"}
    name = url.rsplit("/", 1)[1].removesuffix(".git")
    manifest = await forge.api.get(
        f"/api/v1/repos/miles/{name}/contents/manifest.json?ref=work/atelier"
    )
    assert manifest.status_code == 200
    absent = await forge.api.get(f"/api/v1/repos/miles/{name}/contents/manifest.json?ref=main")
    assert absent.status_code == 404


async def test_one_work_branch_per_workspace_and_replay_is_harmless(forge: Forge) -> None:
    url = await forge.repo()
    await _create(forge, url)
    await _open(forge)

    replay = await _open(forge)
    other = await _open(forge, "autre")

    assert (replay.status_code, replay.json()["outcome"]) == (200, None)
    assert (other.status_code, other.json()["detail"]) == (409, "branche_de_travail_existante")
    assert set(await forge.branches(url)) == {"main", "work/atelier"}


async def test_repository_that_became_inaccessible_designates_access(forge: Forge) -> None:
    await _create(forge, await forge.repo())
    await forge.portal.client.put("/api/secrets/git-ecriture/value", json={"value": "jeton-perime"})

    refused = await _open(forge)

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"code": "acces_depot", "reason": "identifiants"}
    workspace = (await forge.portal.client.get(f"{ROUTE}/retrait")).json()
    assert workspace["work_branch"] is None
