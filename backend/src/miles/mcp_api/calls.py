from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import structlog
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from starlette.requests import Request

from miles.apikeys.model import KEY_DIRECTORY, KeyPrincipal
from miles.chains.service import ChainInUseError, ChainNotFoundError
from miles.datamodels.grammar import ModelGrammarError, ModelSyntaxError
from miles.datamodels.service import ModelInUseError, ModelNotFoundError
from miles.events.model import DelegatedAuthor
from miles.mcp_api.auth import ACTOR_STATE, PRINCIPAL_STATE, SERVICES_STATE
from miles.mcp_api.errors import refusal, refusal_code
from miles.obo.service import Actor
from miles.transform.api_transform import step_problem_out
from miles.transform.chain import ChainInvalidError
from miles.workspaces.model import (
    BranchNotFoundError,
    RepositoryUnavailableError,
    WorkspaceConflictError,
    WorkspaceInputError,
    WorkspaceNotFoundError,
)

log = structlog.get_logger(__name__)

T = TypeVar("T")
# Ce qu'un nom ou un e-mail lu ailleurs ne peut pas porter dans un auteur git.
_UNSAFE_IDENTITY = re.compile(r"[<>\x00-\x1f\x7f]")


@dataclass(frozen=True)
class Caller:
    """Qui appelle : la clé et ses droits, la personne signée par le portail, les services."""

    principal: KeyPrincipal
    actor: Actor | None
    services: Any

    async def readable(self, workspace_id: str) -> None:
        """Lecture : un workspace hors des droits de la clé n'existe pas pour elle (0d4e4f75)."""
        if not self.principal.can_read(workspace_id):
            visible = sorted(g.workspace_id for g in self.principal.grants)
            raise ToolError(refusal("workspace_inconnu", workspace=workspace_id, existants=visible))

    async def writer(self, workspace_id: str, branch: str | None) -> DelegatedAuthor:
        """Modification : droit d'écriture, et une branche enfant nommée (Gael, 22/10/2026).

        Vérifié avant tout clone, et distinct d'un refus de validation : l'agent doit savoir
        s'il s'est trompé de contenu, de branche ou de clé.
        """
        await self.readable(workspace_id)
        if not self.principal.can_write(workspace_id):
            raise ToolError(refusal("droit_insuffisant", workspace=workspace_id, droit="lecture"))
        entries = await self.services.branches.resolve_list(workspace_id)
        children = [e.slug for e in entries if not e.base]
        if branch is None:
            raise ToolError(refusal("branche_requise", branches=children))
        if any(e.base and e.slug == branch for e in entries):
            raise ToolError(refusal("branche_racine_lecture_seule", branches=children))
        if branch not in children:
            raise ToolError(refusal("branche_inconnue", branche=branch, branches=children))
        return await self._author(workspace_id)

    async def _author(self, workspace_id: str) -> DelegatedAuthor:
        key = self.principal
        if self.actor is None:
            identity = f"{_clean(key.label)} via Miles <{key.key_id}@{KEY_DIRECTORY}.miles.invalid>"
            return DelegatedAuthor(KEY_DIRECTORY, key.key_id, key.key_id, key.label, identity)
        person = self.actor.author
        workspace = await self.services.workspaces.resolve_get(workspace_id)
        signature = None
        if workspace.git_connection_id is not None:
            signature = await self.services.git_identities.resolve_signature(
                person, workspace.git_connection_id
            )
        if signature is not None:
            name, email = signature
        else:
            name = self.actor.display_name
            email = self.actor.email or f"{person.subject}@{person.directory}.miles.invalid"
        identity = f"{_clean(name)} <{_clean(email)}>"
        return DelegatedAuthor(person.directory, person.subject, key.key_id, key.label, identity)

    async def write(
        self,
        tool: str,
        workspace_id: str,
        branch: str | None,
        element: str,
        run: Callable[[DelegatedAuthor], Awaitable[T]],
    ) -> T:
        """Une écriture, tracée avec son verdict, refus compris (critère 8)."""
        verdict = "accepte"
        try:
            return await run(await self.writer(workspace_id, branch))
        except ToolError as exc:
            verdict = refusal_code(str(exc))
            raise
        except Exception as exc:
            mapped = tool_refusal(exc)
            if mapped is None:
                verdict = "erreur"
                raise
            verdict = refusal_code(str(mapped))
            raise mapped from None
        finally:
            # Les refus d'abord : un agent qui tourne en rond se voit à ses refus répétés.
            log.info(
                "mcp_ecriture",
                tool=tool,
                workspace=workspace_id,
                branch=branch,
                element=element,
                key=self.principal.key_id,
                actor=None if self.actor is None else self.actor.author.subject,
                verdict=verdict,
            )


def caller_of(ctx: Context[Any, Request]) -> Caller:
    request = ctx.request_context.request
    principal = None if request is None else getattr(request.state, PRINCIPAL_STATE, None)
    if request is None or principal is None:
        # Inatteignable derrière ApiKeyAuth : fermé quand même, si la garde venait à manquer.
        raise ToolError(refusal("cle_requise"))
    actor = getattr(request.state, ACTOR_STATE, None)
    return Caller(principal, actor, getattr(request.state, SERVICES_STATE))


def tool_refusal(exc: Exception) -> ToolError | None:
    """Les refus des services, dans la forme que reçoit l'agent ; None pour un vrai défaut."""
    detail: dict[str, Any] | None = None
    code = ""
    if isinstance(exc, ModelSyntaxError):
        code, detail = (
            "yaml_invalide",
            {"message": exc.message, "line": exc.line, "column": exc.column},
        )
    elif isinstance(exc, ModelGrammarError):
        problems = [{"path": p.path, "code": p.code, "detail": p.detail} for p in exc.problems]
        code, detail = "modele_non_conforme", {"problems": problems}
    elif isinstance(exc, ChainInvalidError):
        problems = [step_problem_out(p).model_dump() for p in exc.problems]
        code, detail = "chaine_invalide", {"problems": problems}
    elif isinstance(exc, ModelInUseError):
        code, detail = "modele_utilise", {"par": exc.users}
    elif isinstance(exc, ChainInUseError):
        code, detail = "chaine_utilisee", {"par": exc.users}
    elif isinstance(exc, WorkspaceInputError):
        code, detail = "champ_invalide", {"champ": exc.field, "raison": exc.reason}
    elif isinstance(exc, WorkspaceConflictError):
        code, detail = exc.code, {}
    elif isinstance(exc, RepositoryUnavailableError):
        code, detail = "acces_depot", {"raison": exc.reason}
    elif isinstance(exc, (ModelNotFoundError, ChainNotFoundError)):
        code, detail = "element_inconnu", {"element": str(exc)}
    elif isinstance(exc, BranchNotFoundError):
        code, detail = "branche_inconnue", {"branche": str(exc)}
    elif isinstance(exc, WorkspaceNotFoundError):
        code, detail = "workspace_inconnu", {}
    if detail is None:
        return None
    return ToolError(refusal(code, **detail))


def _clean(text: str) -> str:
    return _UNSAFE_IDENTITY.sub("", text).strip()[:100] or "inconnu"
