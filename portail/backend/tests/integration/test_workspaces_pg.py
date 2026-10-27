from __future__ import annotations

import base64
import json
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

ROUTE = "/api/workspaces"
VALID_MANIFEST = json.dumps({"format_version": 1, "min_app_version": None, "capabilities": []})


@dataclass
class Forge:
    portal: PortalStack
    api: httpx.AsyncClient
    base: str

    @property
    def client(self) -> httpx.AsyncClient:
        return self.portal.client

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

    async def seed_branch(self, url: str, branch: str, files: dict[str, str]) -> None:
        """Pose `branch` dans le dépôt avec `files` : la branche qui préexiste à Miles."""
        name = url.rsplit("/", 1)[1].removesuffix(".git")
        created = await self.api.post(
            f"/api/v1/repos/miles/{name}/branches", json={"new_branch_name": branch}
        )
        assert created.status_code == 201, created.text
        for path, content in files.items():
            written = await self.api.post(
                f"/api/v1/repos/miles/{name}/contents/{path}",
                json={
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": branch,
                    "message": f"semis {path}",
                },
            )
            assert written.status_code == 201, written.text

    async def commits_on(self, url: str, branch: str) -> int:
        name = url.rsplit("/", 1)[1].removesuffix(".git")
        listed = await self.api.get(
            f"/api/v1/repos/miles/{name}/commits", params={"sha": branch, "limit": 50}
        )
        return len(listed.json())

    async def tags(self, url: str) -> list[str]:
        name = url.rsplit("/", 1)[1].removesuffix(".git")
        return [t["name"] for t in (await self.api.get(f"/api/v1/repos/miles/{name}/tags")).json()]


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
    base = env("MILES_TEST_GITEA_URL")
    headers = {"Authorization": f"token {env('MILES_TEST_GITEA_TOKEN')}"}
    async with (
        open_portal_stack(blank_db, tmp_path) as portal,
        httpx.AsyncClient(base_url=base, headers=headers) as api,
    ):
        wire_git(portal, (base.split("://", 1)[1],))
        for slug, value in (
            ("git-ecriture", env("MILES_TEST_GITEA_TOKEN")),
            ("git-lecture", env("MILES_TEST_GITEA_READ_TOKEN")),
            ("git-faux", "jeton-invalide"),
        ):
            await add_secret(portal.client, slug, "GIT_TOKEN", value)
        # Une connexion par jeton : c'est la connexion qui porte l'accès depuis le 21/10.
        for cid, token in (("forge", "git-ecriture"), ("lecture", "git-lecture")):
            await add_connection(portal.client, cid, base, token_secret_slug=token)
        await add_connection(portal.client, "faux", base, token_secret_slug="git-faux")
        yield Forge(portal, api, base)


async def _with_repo(forge: Forge, url: str, connection: str = "forge") -> httpx.Response:
    await create_workspace(forge.client)
    return await set_repository(forge.client, url, connection)


async def test_workspace_is_created_by_its_name_alone_without_repository(forge: Forge) -> None:
    created = await create_workspace(forge.client)

    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["id"], body["name"], body["repo_url"], body["git_connection_id"]) == (
        "retrait",
        "Nom retrait",
        None,
        None,
    )


async def test_replaying_the_creation_creates_nothing_and_says_so(forge: Forge) -> None:
    await create_workspace(forge.client)

    again = await create_workspace(forge.client)
    other = await forge.client.post(ROUTE, json={"id": "retrait", "name": "Autre"})

    assert (again.status_code, again.headers["x-miles-already-exists"]) == (200, "true")
    assert (other.status_code, other.json()["detail"]) == (409, "identifiant_pris")
    assert await forge.portal.pool.fetchval("SELECT count(*) FROM workspaces") == 1


async def test_empty_repository_gets_main_then_is_recorded_after_five_rights(forge: Forge) -> None:
    url = await forge.repo()

    recorded = await _with_repo(forge, url)

    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert (body["repo_url"], body["git_connection_id"]) == (url, "forge")
    assert body["last_check"]["all_passed"] is True
    assert [c["right"] for c in body["last_check"]["checks"]] == [
        "lire",
        "creer_branche",
        "pousser",
        "poser_tag",
        "supprimer_branche",
    ]
    assert body["last_check"]["initialized_branch"] == "main"
    assert await forge.branches(url) == ["main"] and await forge.tags(url) == []


async def test_replaying_the_repository_tests_nothing_again(forge: Forge) -> None:
    url = await forge.repo()
    await _with_repo(forge, url)

    again = await set_repository(forge.client, url, "forge")
    checks = "SELECT count(*) FROM events WHERE type = 'workspace.access_checked'"

    assert (again.status_code, again.headers["x-miles-already-exists"]) == (200, "true")
    assert await forge.portal.pool.fetchval(checks) == 1


async def test_repository_outside_the_connection_address_is_refused_before_any_attempt(
    forge: Forge,
) -> None:
    await add_connection(
        forge.client, "autre-org", f"{forge.base}/autre", token_secret_slug="git-ecriture"
    )
    await create_workspace(forge.client)

    refused = await set_repository(forge.client, await forge.repo(), "autre-org")

    assert refused.json()["detail"] == {"field": "repo_url", "reason": "hors_connexion"}
    checks = "SELECT count(*) FROM events WHERE type = 'workspace.access_checked'"
    assert await forge.portal.pool.fetchval(checks) == 0


async def test_same_repository_cannot_serve_two_workspaces(forge: Forge) -> None:
    url = await forge.repo()
    await _with_repo(forge, url)
    await create_workspace(forge.client, "depot")

    other = await set_repository(forge.client, url.replace("/miles/", "/MILES/"), "forge", "depot")

    assert (other.status_code, other.json()["detail"]) == (409, "depot_deja_associe")


@pytest.mark.parametrize(
    ("connection", "right", "reason"),
    [
        ("faux", "lire", "identifiants"),
        ("lecture", "creer_branche", "droit_refuse"),
    ],
)
async def test_insufficient_access_records_nothing_and_names_the_right(
    forge: Forge, connection: str, right: str, reason: str
) -> None:
    refused = await _with_repo(forge, await forge.repo(), connection)

    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert (detail["code"], detail["right"], detail["reason"]) == (
        "acces_insuffisant",
        right,
        reason,
    )
    workspace = (await forge.client.get(f"{ROUTE}/retrait")).json()
    assert (workspace["repo_url"], workspace["git_connection_id"]) == (None, None)


async def test_missing_repository_is_named(forge: Forge) -> None:
    refused = await _with_repo(forge, f"{forge.base}/miles/absent-{random.token_hex(3)}.git")

    assert refused.json()["detail"]["reason"] == "depot_inexistant"


async def test_protection_on_the_verification_pattern_is_explained(forge: Forge) -> None:
    url = await forge.repo(auto_init=True)
    name = url.rsplit("/", 1)[1].removesuffix(".git")
    protection = {"rule_name": "miles-verification-*", "enable_push": False}
    protected = await forge.api.post(
        f"/api/v1/repos/miles/{name}/branch_protections", json=protection
    )
    assert protected.status_code == 201

    refused = await _with_repo(forge, url)

    detail = refused.json()["detail"]
    assert (detail["right"], detail["reason"]) == ("creer_branche", "protection")
    assert detail["report"]["residual_branch"] in (None, detail["report"]["branch"])


async def test_unknown_connection_is_refused(forge: Forge) -> None:
    await create_workspace(forge.client)

    refused = await set_repository(forge.client, await forge.repo(), "absente")

    assert refused.json()["detail"] == {"field": "git_connection_id"}


async def test_security_service_is_set_then_removed_from_the_settings(forge: Forge) -> None:
    await create_workspace(forge.client)
    await forge.portal.pool.execute(
        "INSERT INTO security_services (id, kind, base_url, realm, client_id,"
        " client_secret_slug, created_at, updated_at) VALUES ('racine', 'keycloak',"
        " 'https://security.invalid', 'miles', 'miles', 'git-faux', now(), now())"
    )
    route = f"{ROUTE}/retrait/security-service"

    unknown = await forge.client.put(route, json={"security_service_id": "absent"})
    chosen = await forge.client.put(route, json={"security_service_id": "racine"})
    removed = await forge.client.put(route, json={"security_service_id": None})

    assert unknown.json()["detail"] == {"field": "security_service_id"}
    assert chosen.json()["security_service_id"] == "racine"
    assert removed.json()["security_service_id"] is None


async def test_git_gestures_are_refused_until_a_repository_is_recorded(forge: Forge) -> None:
    await create_workspace(forge.client)

    recheck = await forge.client.post(
        f"{ROUTE}/retrait/access-check", json={"verification_suffix": suffix()}
    )
    opened = await forge.client.post(f"{ROUTE}/retrait/work-branch", json={"name": "atelier"})

    assert (recheck.status_code, recheck.json()["detail"]) == (409, "depot_non_configure")
    assert (opened.status_code, opened.json()["detail"]) == (409, "depot_non_configure")


async def test_access_can_be_rechecked_from_the_workspace_and_is_journaled(forge: Forge) -> None:
    await _with_repo(forge, await forge.repo())

    report = await forge.client.post(
        f"{ROUTE}/retrait/access-check", json={"verification_suffix": "0badc0de"}, timeout=120
    )
    rows = await forge.portal.pool.fetch(
        "SELECT e.type, e.author_subject FROM events e"
        " JOIN event_objects o ON o.event_id = e.id WHERE o.object_kind = 'workspace'"
        " ORDER BY o.sequence"
    )

    assert report.json()["branch"] == "miles-verification-0badc0de"
    assert report.json()["all_passed"] is True
    assert [(r["type"], r["author_subject"]) for r in rows] == [
        ("workspace.created", "admin"),
        ("workspace.access_checked", "admin"),
        ("workspace.repository_set", "admin"),
        ("workspace.access_checked", "admin"),
    ]


async def test_connection_in_use_cannot_be_deleted_nor_its_token(forge: Forge) -> None:
    await _with_repo(forge, await forge.repo())

    connection = await forge.client.delete("/api/git-connections/forge")
    token = await forge.client.delete("/api/secrets/git-ecriture")

    assert connection.json()["detail"] == {"code": "utilise", "by": ["retrait"]}
    assert token.json()["detail"]["consumers"] == [{"kind": "git_connection", "id": "forge"}]


async def test_deleting_a_workspace_forgets_it_without_touching_the_repository(
    forge: Forge,
) -> None:
    """Suppression côté back-office : Miles oublie, le dépôt garde tout."""
    url = await forge.repo()
    await _with_repo(forge, url)
    await _open(forge)
    branches_before = set(await forge.branches(url))

    deleted = await forge.client.delete(f"{ROUTE}/retrait", timeout=120)
    listed = await forge.client.get(ROUTE)

    assert deleted.status_code == 204, deleted.text
    assert listed.json() == []
    # Le dépôt n'est pas une donnée de Miles : ses branches sont intactes.
    assert set(await forge.branches(url)) == branches_before
    # La cascade a bien emporté ce qui pendait au workspace.
    rows = await forge.portal.pool.fetchval(
        "SELECT count(*) FROM workspace_work_branches WHERE workspace_id = $1", "retrait"
    )
    assert rows == 0
    # Le journal garde la trace de ce qui a disparu.
    kept = await forge.portal.pool.fetchval(
        "SELECT count(*) FROM events WHERE type = 'workspace.deleted'"
    )
    assert kept == 1


async def test_deleting_an_unknown_workspace_is_a_named_refusal(forge: Forge) -> None:
    refused = await forge.client.delete(f"{ROUTE}/fantome")

    assert (refused.status_code, refused.json()["detail"]) == (404, "workspace_inconnu")


async def _open(
    forge: Forge, name: str = "atelier", *, adopt: bool | None = None
) -> httpx.Response:
    body: dict[str, object] = {"name": name}
    if adopt is not None:
        body["adopt_existing"] = adopt
    return await forge.client.post(f"{ROUTE}/retrait/work-branch", json=body, timeout=120)


async def _stored_outcome(forge: Forge) -> str | None:
    return await forge.portal.pool.fetchval(
        "SELECT outcome FROM workspace_work_branches WHERE workspace_id = $1", "retrait"
    )


async def test_existing_branch_is_refused_then_taken_over_on_demand(forge: Forge) -> None:
    """Le cas du recâblage : la branche préexiste, conforme. On la lie sans rien y écrire.

    Écrit « reprise » en base : la contrainte de 0023 est donc éprouvée par le vrai
    chemin, et pas seulement en SQL. Une contrainte trop étroite coincerait le workspace,
    la branche étant déjà poussée quand l'INSERT échoue.
    """
    url = await forge.repo(auto_init=True)
    await forge.seed_branch(
        url, "back/retrait/atelier", {"manifest.json": VALID_MANIFEST, "domains/.gitkeep": ""}
    )
    await _with_repo(forge, url)
    before = await forge.commits_on(url, "back/retrait/atelier")

    refused = await _open(forge)
    taken = await _open(forge, adopt=True)

    assert (refused.status_code, refused.json()["detail"]) == (409, "branche_existante")
    assert taken.status_code == 201, taken.text
    assert taken.json()["outcome"] == "reprise"
    assert taken.json()["workspace"]["work_branch"] == "back/retrait/atelier"
    assert await _stored_outcome(forge) == "reprise"
    # « elle n'a pas été touchée » : aucun commit de plus sur la branche reprise.
    assert await forge.commits_on(url, "back/retrait/atelier") == before


async def test_taking_over_an_empty_existing_branch_records_that_it_preexisted(
    forge: Forge,
) -> None:
    url = await forge.repo(auto_init=True)
    await forge.seed_branch(url, "back/retrait/atelier", {})
    await _with_repo(forge, url)

    taken = await _open(forge, adopt=True)

    assert taken.status_code == 201, taken.text
    # Surtout pas « initialisee » : la branche préexistait, le journal doit le dire.
    assert taken.json()["outcome"] == "reprise_initialisee"
    assert await _stored_outcome(forge) == "reprise_initialisee"


async def test_work_branch_opens_once_a_repository_is_recorded(forge: Forge) -> None:
    url = await forge.repo()
    await _with_repo(forge, url)

    opened = await _open(forge)
    replay = await _open(forge)
    other = await _open(forge, "autre")

    assert opened.status_code == 201
    assert (opened.json()["outcome"], opened.json()["workspace"]["work_branch"]) == (
        "initialisee",
        "back/retrait/atelier",
    )
    assert (replay.status_code, replay.json()["outcome"]) == (200, None)
    assert (other.status_code, other.json()["detail"]) == (409, "branche_de_travail_existante")
    assert set(await forge.branches(url)) == {"main", "back/retrait/atelier"}


async def test_repository_cannot_change_under_an_open_work_branch(forge: Forge) -> None:
    await _with_repo(forge, await forge.repo())
    await _open(forge)

    refused = await set_repository(forge.client, await forge.repo(), "forge")

    assert (refused.status_code, refused.json()["detail"]) == (409, "branche_de_travail_existante")


async def test_repository_that_became_inaccessible_designates_access(forge: Forge) -> None:
    await _with_repo(forge, await forge.repo())
    await forge.client.put("/api/secrets/git-ecriture/value", json={"value": "jeton-perime"})

    refused = await _open(forge)

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"code": "acces_depot", "reason": "identifiants"}
