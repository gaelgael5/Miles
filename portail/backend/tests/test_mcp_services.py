"""La surface de services que les primitives MCP atteignent est DÉCLARÉE, et exhaustive.

`McpServices` ferme le trou mesuré le 16/11/2026 : `Caller.services` était `Any`, donc
mypy ne voyait rien de ce qu'une primitive demandait à un service. Mais un `Protocol` ne
refuse pas un attribut de plus sur l'objet réel — l'`app.state` en porte des dizaines.
Un service consommé et non déclaré retomberait donc sur un attribut que mypy ne connaît
pas… et mypy le dirait. Ce que mypy ne dirait PAS, c'est l'inverse : une déclaration qui
ne sert plus, ou une primitive écrite pour lire un attribut au travers d'un autre chemin.

Ces tests lisent donc le code de `mcp_api` par `ast` et comparent ce qu'il CONSOMME à ce
que le protocole DÉCLARE. Les deux ensembles doivent être égaux : la liste dit alors
exactement ce que la surface MCP touche, et c'est à ce titre qu'on peut la lire pour
savoir ce qu'un agent peut atteindre.
"""

from __future__ import annotations

import ast
import pathlib

from miles.mcp_api.services import McpServices

MCP_API = pathlib.Path(__file__).resolve().parents[1] / "src" / "miles" / "mcp_api"
# Les deux portes d'entrée de la surface : `Caller.services` (le champ typé) et
# `services_of(ctx)` / `caller_services(state)` (les fabriques du serveur).
GATEWAYS = {"services_of", "caller_services"}


def _modules() -> list[tuple[str, ast.Module]]:
    return [
        (path.name, ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(MCP_API.glob("*.py"))
    ]


def _consumed() -> dict[str, set[str]]:
    """Les attributs lus sur la surface de services, par module qui les lit."""
    found: dict[str, set[str]] = {}
    for name, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            inner = node.value
            through_field = isinstance(inner, ast.Attribute) and inner.attr == "services"
            through_gateway = (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id in GATEWAYS
            )
            if through_field or through_gateway:
                found.setdefault(name, set()).add(node.attr)
    return found


def _declared() -> set[str]:
    return set(McpServices.__annotations__)


def test_tout_ce_que_les_primitives_consomment_est_declare() -> None:
    """Le sens utile du protocole : il n'y a pas de service atteint « par ailleurs ».

    Si ce test rougit, ce n'est pas lui qu'il faut corriger : c'est `McpServices` qui doit
    gagner le service, avec son type réel — sans quoi mypy ne verra rien de ce que la
    primitive en fait.
    """
    consumed = {attr for attrs in _consumed().values() for attr in attrs}

    assert consumed <= _declared(), sorted(consumed - _declared())


def test_le_protocole_ne_declare_rien_que_personne_ne_consomme() -> None:
    """L'autre sens, que mypy ne dit pas : la liste doit rester VRAIE.

    Une déclaration qui ne sert plus ferait croire que la surface MCP touche un service
    qu'elle ne touche pas — et c'est cette liste qu'on lit pour le savoir.
    """
    consumed = {attr for attrs in _consumed().values() for attr in attrs}

    assert _declared() <= consumed, sorted(_declared() - consumed)


def test_la_surface_consommee_est_celle_qu_on_attend() -> None:
    """Jeu d'essai DISCRIMINANT : les deux tests ci-dessus sont verts sur deux ensembles
    vides. Celui-ci dit que la lecture par `ast` trouve bien quelque chose, et quoi."""
    consumed = _consumed()

    assert consumed["tools_schemas.py"] == {"data_models", "domains"}
    assert consumed["tools_chains.py"] == {"chains", "transform_budget"}
    assert consumed["tools_events.py"] == {"workflow_events"}
    # `calls.py` porte les gestes communs : droits, branche, identité git de la personne.
    assert consumed["calls.py"] == {"branches", "git_identities", "workspaces"}
    assert len(_declared()) == 14


def test_le_typage_n_est_pris_sur_parole_qu_a_un_seul_endroit() -> None:
    """Critère 3 : un seul `cast`, nommé et commenté.

    Lu dans le TEXTE et non par `ast` : un `cast` écrit autrement — importé sous un alias,
    appelé par son module — doit aussi se voir. Un seul endroit où l'on affirme, c'est
    aussi un seul endroit à relire le jour où `app.py` change de câblage.
    """
    with_cast = [
        path.name
        for path in sorted(MCP_API.glob("*.py"))
        if "cast(" in path.read_text(encoding="utf-8")
    ]

    assert with_cast == ["services.py"]
