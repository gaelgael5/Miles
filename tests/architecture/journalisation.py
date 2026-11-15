"""Les appels de journalisation qui passent la clef que structlog se réserve.

`structlog` range le MESSAGE sous la clef `event` : `log.info("x", event=y)` lève un
`TypeError` (« got multiple values for argument 'event' ») à l'EXÉCUTION, jamais au lint
ni au typage. Le 15/11/2026, trois appels de `workflowevents/service.py` le faisaient :
déclarer un type d'event écrivait le commit, puis répondait 500 — et aucune suite
unitaire ne passait par là. Le piège est nommé dans la skill `python` ; une phrase ne
l'avait pas empêché, d'où cette lecture de l'arbre syntaxique, dans les quatre racines.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

# Les méthodes d'un logger structlog qui prennent le message en premier argument.
NIVEAUX = frozenset({"debug", "info", "warning", "warn", "error", "exception", "critical", "msg"})
CLEF_RESERVEE = "event"
RACINES = (
    "portail/backend/src",
    "enrolement/backend/src",
    "environnement/backend/src",
    "socle/python/src",
)


@dataclass(frozen=True)
class Appel:
    fichier: str
    ligne: int

    def __str__(self) -> str:
        return f"{self.fichier}:{self.ligne}"


def resolve_appels_fautifs(depot: Path) -> tuple[Appel, ...]:
    """Tout `<x>.<niveau>(..., event=...)` des sources des produits et du socle.

    Large à dessein : on ne cherche pas à prouver que `<x>` est un logger structlog. Un
    autre objet dont une méthode s'appellerait `info` et prendrait `event` en mot-clef
    serait signalé à tort — et se renommerait sans dommage, ce qui vaut mieux qu'une
    garde qui manquerait un logger obtenu autrement que par `get_logger`.
    """
    trouves: list[Appel] = []
    for racine in RACINES:
        for fichier in sorted((depot / racine).rglob("*.py")):
            arbre = ast.parse(fichier.read_text(encoding="utf-8"))
            for node in ast.walk(arbre):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in NIVEAUX
                    and any(kw.arg == CLEF_RESERVEE for kw in node.keywords)
                ):
                    trouves.append(Appel(str(fichier.relative_to(depot)), node.lineno))
    return tuple(trouves)
