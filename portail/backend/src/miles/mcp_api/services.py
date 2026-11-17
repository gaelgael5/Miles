"""Ce que la surface MCP consomme de l'état de l'application, et rien d'autre.

`Caller.services` portait l'`app.state` de FastAPI, dont les attributs ne sont pas
déclarés : il était donc `Any`, et **mypy ne vérifiait rien** de ce qu'une primitive
demandait à un service — ni le nom de la méthode, ni ses arguments, ni la forme de ce
qu'elle rend. Mesuré le 16/11/2026 : `DataModelsService.resolve_list` est passée d'une
liste à un objet, `list_schemas` a continué de l'itérer, style/types/936 tests unitaires
sont restés verts, et c'est la campagne d'intégration qui l'a dit — 65 minutes plus tard.

Un `Protocol` plutôt qu'une dataclasse à construire : l'`app.state` est structurellement
compatible, donc rien ne change dans `app.py` — qui est le câblage de tout le produit, et
que ce ticket ne doit pas toucher. Le typage reste pris sur parole en UN SEUL endroit,
`caller_services`, et nulle part ailleurs.

**Cette liste doit rester EXHAUSTIVE sur la surface MCP.** Un service consommé et non
déclaré ici rouvrirait le trou là où on croirait l'avoir fermé — et il le rouvrirait en
silence, puisque `Protocol` ne refuse pas un attribut de plus sur l'objet réel. C'est
`tests/test_mcp_services.py` qui tient l'exhaustivité, en lisant les attributs que les
modules de `mcp_api` nomment.
"""

from __future__ import annotations

from typing import Protocol, cast

from miles.accounts.service import AccountsService
from miles.chains.service import ChainsService
from miles.datamodels.service import DataModelsService
from miles.identities.service import GitIdentitiesService
from miles.transform.api_catalog import CatalogService
from miles.workflowevents.service import WorkflowEventsService
from miles.workshop.branches import BranchesService
from miles.workshop.domains_service import DomainsService
from miles.workshop.holds import BranchHoldsService
from miles.workshop.targeted import TargetedReads
from miles.workshop.trads_keys import TradsKeysService
from miles.workshop.trads_service import TradsService
from miles.workspaces.service import WorkspacesService


class McpServices(Protocol):
    """Les services que les primitives MCP atteignent, avec leur type réel.

    Seulement ceux-là, et c'est voulu : déclarer tout l'`app.state` ferait de ce fichier
    une deuxième description du câblage, qui divergerait. Ici, la liste DIT ce que la
    surface MCP consomme — on la lit pour savoir ce qu'un agent peut toucher.
    """

    accounts: AccountsService
    branch_holds: BranchHoldsService
    branches: BranchesService
    chains: ChainsService
    data_models: DataModelsService
    domains: DomainsService
    git_identities: GitIdentitiesService
    targeted_reads: TargetedReads
    template_catalog: CatalogService
    trads: TradsService
    trads_keys: TradsKeysService
    workflow_events: WorkflowEventsService
    workspaces: WorkspacesService
    # Pas un service : le plafond d'exécution d'un template, posé par les réglages
    # (`settings.transform_budget`). Déclaré ici quand même, parce que `try_chain` le lit
    # sur le même objet — et qu'un entier lu comme autre chose se verrait aussi mal.
    transform_budget: int


def caller_services(state: object) -> McpServices:
    """L'`app.state` vu comme la surface MCP. LE seul endroit pris sur parole.

    `app.state` est un `State` de Starlette : un sac d'attributs posés à l'exécution par
    `app.py`, qu'aucun typage ne décrit. Ce `cast` est donc une affirmation, et c'est
    pourquoi il est seul et nommé : si `app.py` cessait de poser l'un de ces services, ni
    mypy ni ce cast ne le verraient — c'est `tests/test_cablage.py` qui le tient, en
    rougissant sur un service posé et câblé dans aucun test d'intégration.
    """
    return cast(McpServices, state)
