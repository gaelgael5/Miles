from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from structlog.testing import capture_logs

from miles.apikeys.model import Access, Grant, KeyPrincipal
from miles.events.model import DelegatedAuthor, EventAuthor
from miles.mcp_api.calls import Caller, tool_refusal
from miles.obo.service import Actor
from miles.workspaces.model import HoldRequiredError, WorkspaceConflictError

KEY = KeyPrincipal(
    "a" * 32, "Gateway", (Grant("retrait", Access.WRITE), Grant("caisse", Access.READ))
)


@dataclass(frozen=True)
class Entry:
    slug: str
    base: bool


class Branches:
    async def resolve_list(self, workspace_id: str) -> list[Entry]:
        return [Entry("atelier", True), Entry("edition", False)]


class Workspaces:
    async def resolve_get(self, workspace_id: str) -> Any:
        return SimpleNamespace(git_connection_id="forge")


class Identities:
    def __init__(self, signature: tuple[str, str] | None) -> None:
        self.signature = signature

    async def resolve_signature(self, viewer: EventAuthor, connection: str) -> Any:
        return self.signature


def _caller(actor: Actor | None = None, signature: tuple[str, str] | None = None) -> Caller:
    services = SimpleNamespace(
        branches=Branches(), workspaces=Workspaces(), git_identities=Identities(signature)
    )
    return Caller(KEY, actor, services)


def _code(exc: pytest.ExceptionInfo[ToolError]) -> Any:
    return json.loads(str(exc.value))


async def test_the_key_alone_cannot_write_since_writes_act_as_a_person() -> None:
    with pytest.raises(ToolError) as refused:
        await _caller().writer("retrait", "edition")

    assert _code(refused) == {"code": "personne_requise"}


async def test_the_key_alone_reads_as_itself_and_a_person_as_themselves() -> None:
    lea = Actor(EventAuthor("maison", "sub-lea"), "Léa", None)

    assert _caller().viewer == EventAuthor("apikey", "a" * 32)
    assert _caller(lea).viewer == EventAuthor("maison", "sub-lea")


async def test_a_signed_person_signs_with_their_git_identity_when_they_have_one() -> None:
    lea = Actor(EventAuthor("maison", "sub-lea"), "Léa <la vraie>", "lea@exemple.invalid")

    with_git = await _caller(lea, ("Léa Martin", "lea@forge.invalid")).writer("retrait", "edition")
    without = await _caller(lea).writer("retrait", "edition")

    assert (with_git.directory, with_git.subject) == ("maison", "sub-lea")
    assert with_git.commit_identity == "Léa Martin <lea@forge.invalid>"
    # Les chevrons d'un nom lu ailleurs ne forgent pas un autre e-mail d'auteur.
    assert without.commit_identity == "Léa la vraie <lea@exemple.invalid>"


@pytest.mark.parametrize(
    ("workspace", "branch", "expected"),
    [
        (
            "caisse",
            "edition",
            {"code": "droit_insuffisant", "workspace": "caisse", "droit": "lecture"},
        ),
        (
            "stock",
            "edition",
            {"code": "workspace_inconnu", "workspace": "stock", "existants": ["caisse", "retrait"]},
        ),
        ("retrait", None, {"code": "branche_requise", "branches": ["edition"]}),
        ("retrait", "atelier", {"code": "branche_racine_lecture_seule", "branches": ["edition"]}),
        ("retrait", "x", {"code": "branche_inconnue", "branche": "x", "branches": ["edition"]}),
    ],
)
async def test_writer_refusals_come_before_any_clone(
    workspace: str, branch: str | None, expected: dict[str, Any]
) -> None:
    with pytest.raises(ToolError) as refused:
        await _caller().writer(workspace, branch)

    assert _code(refused) == expected


async def test_every_write_is_traced_with_its_verdict_refusals_included() -> None:
    async def accepted(author: DelegatedAuthor) -> str:
        return "fait"

    async def conflict(author: DelegatedAuthor) -> str:
        raise WorkspaceConflictError("nom_pris")

    lea = Actor(EventAuthor("maison", "sub-lea"), "Léa", None)
    with capture_logs() as logs:
        assert await _caller(lea).write("t", "retrait", "edition", "x", accepted) == "fait"
        with pytest.raises(ToolError):
            await _caller(lea).write("t", "retrait", "edition", "x", conflict)
        with pytest.raises(ToolError):
            await _caller(lea).write("t", "retrait", None, "x", accepted)

    traced = [(e["verdict"], e["key"]) for e in logs if e["event"] == "mcp_ecriture"]
    assert traced == [("accepte", "a" * 32), ("nom_pris", "a" * 32), ("branche_requise", "a" * 32)]


async def test_a_write_without_the_hold_names_who_holds_the_branch() -> None:
    held = tool_refusal(HoldRequiredError("Bob Martin (bob)"))
    free = tool_refusal(HoldRequiredError(None))

    assert held is not None and json.loads(str(held)) == {
        "code": "prise_de_main_requise",
        "par": "Bob Martin (bob)",
    }
    assert free is not None and json.loads(str(free)) == {
        "code": "prise_de_main_requise",
        "par": None,
    }


async def test_an_unexpected_failure_is_not_disguised_as_a_refusal() -> None:
    assert tool_refusal(RuntimeError("défaut")) is None
