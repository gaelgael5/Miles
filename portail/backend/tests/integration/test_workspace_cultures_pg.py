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
    env,
    set_repository,
    wire_git,
)
from tests.integration.portal_stack import PortalStack, open_portal_stack

pytestmark = pytest.mark.integration

ROUTE = "/api/workspaces"
WID = "retrait"
CULTURES = f"{ROUTE}/{WID}/cultures"
DEFAULT = f"{CULTURES}/default"
MANIFEST = json.dumps({"format_version": 1, "min_app_version": None, "capabilities": []})


@dataclass
class Stack:
    portal: PortalStack
    api: httpx.AsyncClient
    base: str

    @property
    def client(self) -> httpx.AsyncClient:
        return self.portal.client

    async def workspace(self, culture: str = "en-US", wid: str = WID) -> httpx.Response:
        body = {"id": wid, "name": f"Nom {wid}", "default_culture": culture}
        return await self.client.post(ROUTE, json=body)

    async def repo_with_trads(self, files: dict[str, str]) -> None:
        """Un workspace avec un dépôt dont la branche de base porte `files`.

        Le référentiel vit dans git : le refus du changement de culture par défaut ne se
        mesure que contre un vrai dépôt, pas contre la base.
        """
        name = f"cfg-{random.token_hex(4)}"
        created = await self.api.post(
            "/api/v1/user/repos", json={"name": name, "private": True, "auto_init": False}
        )
        assert created.status_code == 201, created.text
        url = f"{self.base}/miles/{name}.git"
        assert (await set_repository(self.client, url, "forge", WID)).status_code == 200
        opened = await self.client.post(
            f"{ROUTE}/{WID}/work-branch", json={"name": "base"}, timeout=120
        )
        assert opened.status_code == 201, opened.text
        branch = opened.json()["workspace"]["work_branch"]
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


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[Stack]:
    base = env("MILES_TEST_GITEA_URL")
    headers = {"Authorization": f"token {env('MILES_TEST_GITEA_TOKEN')}"}
    async with (
        open_portal_stack(blank_db, tmp_path) as portal,
        httpx.AsyncClient(base_url=base, headers=headers) as api,
    ):
        wire_git(portal, (base.split("://", 1)[1],))
        await add_secret(portal.client, "git-ecriture", "GIT_TOKEN", env("MILES_TEST_GITEA_TOKEN"))
        await add_connection(portal.client, "forge", base, token_secret_slug="git-ecriture")
        yield Stack(portal, api, base)


# --- Critère 1 : la culture par défaut est demandée à la création ---


async def test_workspace_cannot_be_created_without_a_default_culture(stack: Stack) -> None:
    refused = await stack.client.post(ROUTE, json={"id": WID, "name": "Nom"})

    assert refused.status_code == 422
    assert (await stack.client.get(ROUTE)).json() == []


async def test_creation_records_the_default_culture_and_no_additional_one(stack: Stack) -> None:
    assert (await stack.workspace("fr-FR")).status_code == 201

    assert (await stack.client.get(CULTURES)).json() == {"default": "fr-FR", "additional": []}


async def test_unknown_default_culture_is_refused_and_the_workspace_is_not_created(
    stack: Stack,
) -> None:
    refused = await stack.workspace("zz-ZZ")

    assert refused.status_code == 422
    assert refused.json()["detail"]["field"] == "default_culture"
    assert (await stack.client.get(ROUTE)).json() == []


async def test_default_culture_shaped_like_a_path_is_refused_before_the_database(
    stack: Stack,
) -> None:
    """Le code devient un segment de `trads/<contexte>/<culture>.yaml` : jamais hors de `trads/`."""
    refused = await stack.workspace("../../../etc/passwd")

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"field": "default_culture", "reason": "forme"}


# --- Critère 9 : le catalogue complet, pas seulement les cultures actives ---


async def test_default_culture_may_be_one_the_application_does_not_display(stack: Stack) -> None:
    """Traduire en thaï n'exige pas de lire le back-office en thaï : ce sont deux listes.

    L'état d'activation se lit en BASE : la discrimination du test est que th-TH ne soit
    pas active, et la route des cultures de l'application n'est pas montée par ce harnais.
    """
    active = await stack.portal.pool.fetchval(
        "SELECT active FROM cultures WHERE code = $1", "th-TH"
    )
    assert active is False

    assert (await stack.workspace("th-TH")).status_code == 201
    assert (await stack.client.get(CULTURES)).json()["default"] == "th-TH"


async def test_additional_culture_may_be_one_the_application_does_not_display(
    stack: Stack,
) -> None:
    await stack.workspace("fr-FR")

    added = await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    assert added.status_code == 200
    assert added.json() == {"default": "fr-FR", "additional": ["ar-MA"]}


# --- Critères 2, 3, 4 : ordre, ajout, refus du doublon ---


async def test_default_culture_comes_first_and_additional_ones_follow_in_a_stable_order(
    stack: Stack,
) -> None:
    await stack.workspace("fr-FR")
    for culture in ("th-TH", "ar-MA", "he-IL"):
        assert (await stack.client.post(CULTURES, json={"culture": culture})).status_code == 200

    listed = (await stack.client.get(CULTURES)).json()

    assert listed["default"] == "fr-FR"
    assert listed["additional"] == ["ar-MA", "he-IL", "th-TH"]


async def test_additional_culture_equal_to_the_default_one_changes_nothing(stack: Stack) -> None:
    """Critère 4 : refusé, et c'est la clé primaire qui le refuse, pas une relecture."""
    await stack.workspace("fr-FR")

    added = await stack.client.post(CULTURES, json={"culture": "fr-FR"})

    assert added.status_code == 200
    assert added.json() == {"default": "fr-FR", "additional": []}


async def test_adding_the_same_additional_culture_twice_is_replayed_without_effect(
    stack: Stack,
) -> None:
    await stack.workspace("fr-FR")
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    again = await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    assert again.json() == {"default": "fr-FR", "additional": ["ar-MA"]}


async def test_unknown_additional_culture_is_refused_by_the_catalogue(stack: Stack) -> None:
    await stack.workspace("fr-FR")

    refused = await stack.client.post(CULTURES, json={"culture": "zz-ZZ"})

    assert refused.status_code == 422
    assert refused.json()["detail"] == {"field": "culture", "reason": "inconnue"}


# --- Critère 7 et 8 : retrait, puis réajout ---


async def test_removing_an_additional_culture_takes_it_off_the_screens(stack: Stack) -> None:
    await stack.workspace("fr-FR")
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    removed = await stack.client.delete(f"{CULTURES}/ar-MA")

    assert removed.status_code == 200
    assert removed.json() == {"default": "fr-FR", "additional": []}


async def test_the_default_culture_cannot_be_removed(stack: Stack) -> None:
    await stack.workspace("fr-FR")

    removed = await stack.client.delete(f"{CULTURES}/fr-FR")

    assert removed.json() == {"default": "fr-FR", "additional": []}


async def test_removing_a_culture_leaves_its_files_in_the_repository(stack: Stack) -> None:
    """Critère 7 : on ne détruit pas un travail de traduction en décochant une case."""
    await stack.workspace("fr-FR")
    await stack.repo_with_trads(
        {"manifest.yaml": MANIFEST, "trads/accueil/ar-MA.yaml": "titre: مرحبا\n"}
    )
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    await stack.client.delete(f"{CULTURES}/ar-MA")

    # Même valeur de retour qu'avant le retrait : la seule chose qui a changé est la liste.
    readded = await stack.client.post(CULTURES, json={"culture": "ar-MA"})
    assert readded.json()["additional"] == ["ar-MA"]
    # Et le fichier est toujours là, donc ses valeurs réapparaissent (critère 8) : le
    # changement de culture par défaut vers ar-MA passe encore sur la clé qu'il porte.
    assert (await stack.client.put(DEFAULT, json={"culture": "ar-MA"})).status_code == 200


# --- Critères 5 et 6 : changer la culture par défaut après coup ---


async def test_default_culture_changes_when_the_referential_is_complete_in_the_target(
    stack: Stack,
) -> None:
    await stack.workspace("fr-FR")
    await stack.repo_with_trads(
        {
            "manifest.yaml": MANIFEST,
            "trads/accueil/fr-FR.yaml": "titre: Bonjour\n",
            "trads/accueil/ar-MA.yaml": "titre: مرحبا\n",
        }
    )
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    changed = await stack.client.put(DEFAULT, json={"culture": "ar-MA"})

    assert changed.status_code == 200
    # L'ancienne devient additionnelle et garde ses valeurs (critère 5).
    assert changed.json() == {"default": "ar-MA", "additional": ["fr-FR"]}


async def test_default_culture_change_is_refused_with_the_count_of_missing_keys(
    stack: Stack,
) -> None:
    await stack.workspace("fr-FR")
    await stack.repo_with_trads(
        {
            "manifest.yaml": MANIFEST,
            "trads/accueil/fr-FR.yaml": "titre: Bonjour\nadieu: Au revoir\n",
            "trads/accueil/ar-MA.yaml": "titre: مرحبا\n",
            "trads/erreurs/fr-FR.yaml": "refus: Refusé\n",
        }
    )
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    refused = await stack.client.put(DEFAULT, json={"culture": "ar-MA"})

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "culture_defaut_incomplete",
        "culture": "ar-MA",
        # `adieu` dans « accueil », `refus` dans « erreurs » : le nombre, pour que l'écran
        # dise l'ampleur du travail et mène à la liste (critère 6).
        "missing": 2,
    }
    assert (await stack.client.get(CULTURES)).json()["default"] == "fr-FR"


async def test_default_culture_change_passes_on_a_workspace_without_a_repository(
    stack: Stack,
) -> None:
    """Rien à lire n'est pas un échec de lecture : son référentiel est vide."""
    await stack.workspace("fr-FR")
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    changed = await stack.client.put(DEFAULT, json={"culture": "ar-MA"})

    assert changed.status_code == 200, changed.text
    assert changed.json() == {"default": "ar-MA", "additional": ["fr-FR"]}


async def test_default_culture_change_to_a_culture_not_yet_in_the_workspace(stack: Stack) -> None:
    await stack.workspace("fr-FR")

    changed = await stack.client.put(DEFAULT, json={"culture": "th-TH"})

    assert changed.json() == {"default": "th-TH", "additional": ["fr-FR"]}


async def test_default_culture_set_to_the_current_one_changes_nothing(stack: Stack) -> None:
    await stack.workspace("fr-FR")

    unchanged = await stack.client.put(DEFAULT, json={"culture": "fr-FR"})

    assert unchanged.json() == {"default": "fr-FR", "additional": []}


async def test_unreadable_trads_file_is_named_rather_than_counted_as_work(stack: Stack) -> None:
    """Une incohérence du dépôt se dit : la compter comme « rien ne manque » accepterait
    un changement de culture par défaut à tort."""
    await stack.workspace("fr-FR")
    await stack.repo_with_trads(
        {"manifest.yaml": MANIFEST, "trads/accueil/fr-FR.yaml": "titre: [non fermé\n"}
    )

    answered = await stack.client.put(DEFAULT, json={"culture": "th-TH"})

    assert answered.status_code == 422
    assert answered.json()["detail"] == {
        "code": "trads_illisible",
        "path": "trads/accueil/fr-FR.yaml",
        "reason": "yaml illisible",
    }


# --- Critère 10 : les réglages suivent le workspace ---


async def test_two_workspaces_keep_independent_lists(stack: Stack) -> None:
    await stack.workspace("fr-FR", WID)
    await stack.workspace("th-TH", "colis")
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    assert (await stack.client.get(CULTURES)).json() == {
        "default": "fr-FR",
        "additional": ["ar-MA"],
    }
    assert (await stack.client.get(f"{ROUTE}/colis/cultures")).json() == {
        "default": "th-TH",
        "additional": [],
    }


async def test_deleting_a_workspace_takes_its_cultures_with_it(stack: Stack) -> None:
    await stack.workspace("fr-FR")
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})

    assert (await stack.client.delete(f"{ROUTE}/{WID}")).status_code == 204

    assert (await stack.client.get(CULTURES)).status_code == 404


async def test_cultures_of_an_unknown_workspace_are_a_named_refusal(stack: Stack) -> None:
    answered = await stack.client.get(f"{ROUTE}/inconnu/cultures")

    assert answered.status_code == 404
    assert answered.json()["detail"] == "workspace_inconnu"


# --- Critère 11 : réservé à qui administre le workspace ---


async def test_cultures_are_closed_without_a_session(stack: Stack) -> None:
    await stack.workspace("fr-FR")
    async with stack.portal.anonymous() as anonymous:
        assert (await anonymous.get(CULTURES)).status_code == 401
        assert (await anonymous.post(CULTURES, json={"culture": "ar-MA"})).status_code == 401
        assert (await anonymous.delete(f"{CULTURES}/ar-MA")).status_code == 401
        assert (await anonymous.put(DEFAULT, json={"culture": "ar-MA"})).status_code == 401


# --- Le journal ---


async def test_each_gesture_is_journaled_with_the_culture(stack: Stack) -> None:
    await stack.workspace("fr-FR")
    await stack.client.post(CULTURES, json={"culture": "ar-MA"})
    await stack.client.put(DEFAULT, json={"culture": "ar-MA"})
    await stack.client.delete(f"{CULTURES}/fr-FR")

    rows = await stack.portal.pool.fetch(
        "SELECT type, properties FROM events WHERE type LIKE 'workspace.culture%'"
        " OR type = 'workspace.default_culture_set' ORDER BY written_at"
    )
    journaled = [(r["type"], _properties(r["properties"])) for r in rows]

    assert ("workspace.culture_added", {"culture": "ar-MA"}) in journaled
    assert (
        "workspace.default_culture_set",
        {"culture": "ar-MA", "previous": "fr-FR"},
    ) in journaled
    assert ("workspace.culture_removed", {"culture": "fr-FR"}) in journaled


def _properties(raw: object) -> dict[str, object]:
    # asyncpg rend une colonne `jsonb` en CHAÎNE, pas en dictionnaire (LESSONS.md).
    return json.loads(raw) if isinstance(raw, str) else dict(raw)  # type: ignore[arg-type]
