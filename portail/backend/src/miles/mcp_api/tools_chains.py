from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field
from starlette.requests import Request

from miles.chains.service import ChainNotFoundError, ChainsService, StoredChain, StoredStep
from miles.mcp_api.calls import Caller, caller_of, tool_refusal
from miles.mcp_api.errors import refusal
from miles.mcp_api.tools_models import ReadBranch, Workspace, WriteBranch
from miles.transform.api_transform import StepIn, run_check

Slug = Annotated[
    str,
    Field(description="Slug de la chaîne : son répertoire transformations/<slug>/, figé."),
]


class StepArg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Nom de l'étape : celui du fichier de son template.")
    template: str = Field(description="Template JSLT de l'étape, dans le profil d'écriture.")
    target: str | None = Field(
        default=None,
        description=(
            "Vide : le résultat devient le message. Sinon, un chemin unique ($.a.b) où poser"
            " le résultat dans le message, objets intermédiaires créés."
        ),
    )
    source_model: str | None = Field(
        default=None,
        description=(
            "URI du modèle que l'étape lit (« miles:/shared/colis »). Sans effet sur"
            " l'exécution ; l'écran s'en sert. OMIS, il est EFFACÉ : save_chain remplace"
            " la chaîne entière."
        ),
    )
    destination_model: str | None = Field(
        default=None,
        description=("URI du modèle que l'étape produit. Même règle : omis, il est effacé."),
    )


Steps = Annotated[list[StepArg], Field(description="Les étapes, dans l'ordre d'application.")]


def _chain(chain: StoredChain) -> dict[str, Any]:
    steps = [
        {
            "name": s.name,
            "template": s.template,
            "target": s.target,
            "source_model": s.source_model,
            "destination_model": s.destination_model,
        }
        for s in chain.steps
    ]
    path = f"transformations/{chain.slug}/"
    return {"slug": chain.slug, "label": chain.label, "path": path, "steps": steps}


async def _chains(caller: Caller) -> ChainsService:
    service: ChainsService = caller.services.chains
    return service


async def _unknown(caller: Caller, workspace_id: str, branch: str | None, slug: str) -> ToolError:
    found = await (await _chains(caller)).resolve_list(caller.viewer, workspace_id, branch=branch)
    slugs = [c if isinstance(c, str) else c.slug for c in found]
    return ToolError(refusal("chaine_inconnue", slug=slug, existants=slugs))


def register(server: MCPServer) -> None:
    @server.tool(
        description=(
            "Liste les chaînes de transformations d'une branche. Une chaîne illisible"
            " (retouchée hors de Miles) apparaît avec label null."
        )
    )
    async def list_chains(
        workspace_id: Workspace, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> list[dict[str, Any]]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            found = await (await _chains(caller)).resolve_list(
                caller.viewer, workspace_id, branch=branch
            )
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return [
            {"slug": c, "label": None, "steps": None}
            if isinstance(c, str)
            else {"slug": c.slug, "label": c.label, "steps": len(c.steps)}
            for c in found
        ]

    @server.tool(description="Lit une chaîne : son libellé et ses étapes, templates compris.")
    async def get_chain(
        workspace_id: Workspace, slug: Slug, ctx: Context[Any, Request], branch: ReadBranch = None
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        await caller.readable(workspace_id)
        try:
            chain = await (await _chains(caller)).resolve_get(
                caller.viewer, workspace_id, slug, branch=branch
            )
        except ChainNotFoundError:
            raise await _unknown(caller, workspace_id, branch, slug) from None
        except Exception as exc:
            raise tool_refusal(exc) or exc from None
        return _chain(chain)

    @server.tool(
        description=(
            "Crée ou remplace une chaîne entière (libellé et étapes) dans une branche enfant,"
            " seulement si toutes ses étapes passent la vérification ; sinon chaine_invalide"
            " rend les écarts de chaque étape avec son rang (0 pour la première)."
        )
    )
    async def save_chain(
        workspace_id: Workspace,
        slug: Slug,
        label: Annotated[str, Field(description="Libellé affiché, sur une ligne.")],
        steps: Steps,
        ctx: Context[Any, Request],
        branch: WriteBranch = None,
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _chains(caller)
        # Les modèles sont RELUS de l'entrée : les laisser tomber ici effaçait, sans un
        # mot, ce que l'écran avait posé — un agent qui ne touche qu'un template suffisait.
        stored = [
            StoredStep(s.name, s.template, s.target, s.source_model, s.destination_model)
            for s in steps
        ]

        async def run(author: Any) -> dict[str, Any]:
            chain, commit = await service.resolve_save(
                author, workspace_id, slug, label, stored, branch=branch
            )
            return _chain(chain) | {"commit": commit, "unchanged": commit is None}

        return await caller.write("save_chain", workspace_id, branch, slug, run)

    @server.tool(
        description=(
            "Supprime une chaîne d'une branche enfant. Refusé (chaine_utilisee) tant qu'une"
            " source de données la désigne : le refus nomme lesquelles."
        )
    )
    async def delete_chain(
        workspace_id: Workspace, slug: Slug, ctx: Context[Any, Request], branch: WriteBranch = None
    ) -> dict[str, Any]:
        caller = caller_of(ctx)
        service = await _chains(caller)

        async def run(author: Any) -> dict[str, Any]:
            try:
                commit = await service.resolve_delete(author, workspace_id, slug, branch=branch)
            except ChainNotFoundError:
                raise await _unknown(caller, workspace_id, branch, slug) from None
            return {"deleted": slug, "commit": commit}

        return await caller.write("delete_chain", workspace_id, branch, slug, run)

    @server.tool(
        description=(
            "Essaie des étapes sur un message d'exemple, sans rien écrire : rend les écarts de"
            " vérification, ou le message après chaque étape, ou l'étape qui échoue et pourquoi."
            " Sans message, la source vaut {}."
        )
    )
    async def try_chain(
        steps: Steps,
        ctx: Context[Any, Request],
        sample: Annotated[Any, Field(description="Message d'entrée (JSON).")] = None,
    ) -> dict[str, Any]:
        # Rien n'est écrit ni lu d'un workspace : la clé suffit, sans droit particulier.
        budget: int = caller_of(ctx).services.transform_budget
        specs = [StepIn(template=s.template, target=s.target) for s in steps]
        return run_check(specs, sample, budget).model_dump()
