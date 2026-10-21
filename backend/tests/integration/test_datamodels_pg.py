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
    wire_git,
)
from tests.integration.portal_stack import PortalStack, open_portal_stack

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces/retrait/data-models"
PERSONNE = "nom: personne\nversion: 1\nproprietes:\n  nom:\n    type: chaine\n"
COLIS = """nom: colis
version: 2
description: Colis tel que le terminal le manipule
proprietes:
  reference:
    type: chaine
    obligatoire: true
  destinataire:
    type: objet
    modele: personne
  etiquettes:
    type: liste
    elements:
      type: chaine
"""


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


@pytest.fixture
async def forge(blank_db: str, tmp_path: Path) -> AsyncIterator[Forge]:
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


async def _create(forge: Forge, content: str, scope: str = "shared") -> httpx.Response:
    return await forge.client.post(ROUTE, json={"scope": scope, "content": content}, timeout=120)


async def test_model_is_written_to_the_work_branch_then_read_back_and_listed(
    forge: Forge,
) -> None:
    await _create(forge, PERSONNE)

    created = await _create(forge, COLIS, scope="suivi")
    read = await forge.client.get(f"{ROUTE}/suivi/colis", timeout=120)
    listed = await forge.client.get(ROUTE, timeout=120)

    assert created.status_code == 201, created.text
    assert created.json() == {
        "scope": "suivi",
        "name": "colis",
        "path": "domains/suivi/messages/colis.yaml",
    }
    assert await forge.file("domains/suivi/messages/colis.yaml") == COLIS
    assert read.json()["content"] == COLIS
    assert [(m["scope"], m["name"]) for m in listed.json()] == [
        ("suivi", "colis"),
        ("shared", "personne"),
    ]
    events = await forge.portal.pool.fetch(
        "SELECT properties->>'path' AS path FROM events WHERE type = 'data_model.created'"
        " ORDER BY written_at"
    )
    assert [e["path"] for e in events] == [
        "shared/messages/personne.yaml",
        "domains/suivi/messages/colis.yaml",
    ]


async def test_replay_writes_nothing_and_a_different_content_is_a_conflict(forge: Forge) -> None:
    await _create(forge, PERSONNE)
    before = await forge.commits()

    replay = await _create(forge, PERSONNE)
    other = await _create(forge, PERSONNE.replace("version: 1", "version: 2"))

    assert (replay.status_code, replay.headers["x-miles-already-exists"]) == (200, "true")
    assert (other.status_code, other.json()["detail"]) == (409, "nom_pris")
    assert await forge.commits() == before


async def test_refusals_write_nothing_and_say_why(forge: Forge) -> None:
    before = await forge.commits()

    syntax = await _create(forge, "nom: x\nproprietes: [\n")
    grammar = await _create(forge, "nom: x\nversion: 1\nproprietes:\n  a:\n    type: texte\n")
    missing = await _create(forge, COLIS)

    assert syntax.status_code == 422
    assert syntax.json()["detail"]["code"] == "yaml_invalide"
    assert syntax.json()["detail"]["line"] is not None
    assert grammar.json()["detail"]["problems"] == [
        {"path": "proprietes.a.type", "code": "type_inconnu", "detail": "texte"}
    ]
    # Un transverse ne voit pas les modèles de domaine, et personne n'existe pas encore.
    assert missing.json()["detail"]["problems"] == [
        {"path": "proprietes.destinataire.modele", "code": "modele_inconnu", "detail": "personne"}
    ]
    assert await forge.commits() == before


async def test_referenced_model_cannot_be_deleted_until_its_user_is(forge: Forge) -> None:
    await _create(forge, PERSONNE)
    await _create(forge, COLIS, scope="suivi")

    refused = await forge.client.delete(f"{ROUTE}/shared/personne", timeout=120)
    user_deleted = await forge.client.delete(f"{ROUTE}/suivi/colis", timeout=120)
    deleted = await forge.client.delete(f"{ROUTE}/shared/personne", timeout=120)
    again = await forge.client.delete(f"{ROUTE}/shared/personne", timeout=120)

    assert refused.json()["detail"] == {
        "code": "utilise",
        "by": ["domains/suivi/messages/colis.yaml"],
    }
    assert (user_deleted.status_code, deleted.status_code) == (204, 204)
    assert await forge.file("shared/messages/personne.yaml") is None
    assert (again.status_code, again.json()["detail"]) == (404, "modele_inconnu")


async def test_missing_work_branch_is_refused_without_creating_one(forge: Forge) -> None:
    deleted = await forge.api.delete(f"/api/v1/repos/miles/{forge.name}/branches/work/atelier")
    assert deleted.status_code == 204

    refused = await _create(forge, PERSONNE)
    branches = await forge.api.get(f"/api/v1/repos/miles/{forge.name}/branches")

    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "branche_de_travail_introuvable",
    )
    assert "work/atelier" not in [b["name"] for b in branches.json()]


async def test_workspace_without_work_branch_is_refused(forge: Forge) -> None:
    await create_workspace(forge.client, "caisse")

    refused = await forge.client.get("/api/workspaces/caisse/data-models")
    bad_scope = await forge.client.post(ROUTE, json={"scope": "../x", "content": PERSONNE})

    assert (refused.status_code, refused.json()["detail"]) == (409, "depot_non_configure")
    assert bad_scope.json()["detail"] == {"field": "scope"}
