from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from openapi_spec_validator import OpenAPIV30SpecValidator, OpenAPIV31SpecValidator

from miles.datamodels.grammar import ModelSyntaxError, load_yaml

# Versions prises en charge au premier lot (latitude du ticket 502b24c2) : les 3.0 et
# 3.1, celles que publient aujourd'hui les tiers. Swagger 2.0 et 3.2 sont refusés en
# nommant la version rencontrée, plutôt qu'à moitié lus.
SUPPORTED = {"3.0": OpenAPIV30SpecValidator, "3.1": OpenAPIV31SpecValidator}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
MAX_PROBLEMS = 50
# Un contrat de tiers dépasse vite la taille d'un modèle ; la borne reste, pour qu'un
# dépôt ne puisse pas épuiser la mémoire du back-office.
MAX_CONTRACT_BYTES = 2 * 1024 * 1024


class ContractSyntaxError(ValueError):
    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.message, self.line, self.column = message, line, column


class UnsupportedVersionError(ValueError):
    def __init__(self, found: str | None) -> None:
        super().__init__(f"version OpenAPI non prise en charge : {found}")
        self.found = found


@dataclass(frozen=True)
class ContractProblem:
    """Écart à la spécification ; `path` désigne l'endroit, en notation JSONPath."""

    path: str
    message: str


class ContractInvalidError(ValueError):
    def __init__(self, problems: list[ContractProblem]) -> None:
        super().__init__(f"{len(problems)} écart(s) à la spécification OpenAPI")
        self.problems = problems


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    operation_id: str | None


@dataclass(frozen=True)
class ParsedContract:
    title: str
    openapi: str
    operations: tuple[Operation, ...]
    # Le document lu, dont se dérivent les modèles du contrat (story 47f55d8b).
    document: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


def read_contract(text: str) -> ParsedContract:
    """Lit un contrat OpenAPI SANS le confronter à la spécification.

    « On valide les documents seulement à la sauvegarde et au commit » (Gael,
    18/11/2026). La confrontation à la spécification coûte **1 852 ms** sur le contrat
    réel de la branche `test1` — 60 % du temps de la route des contrats, mesuré le
    18/11/2026 (enabler ee2c3665) —, et son verdict ne peut changer qu'au prix d'un
    commit fait hors de Miles. L'AFFICHAGE l'évite donc ; `parse_contract` la garde pour
    l'import, l'aperçu et la validation de branche.

    Ce qui reste ici n'est pas un allègement par confort : la syntaxe, la version prise en
    charge et le refus des références externes sont ce qui permet de LIRE le document, et
    ils coûtent 4 ms. Le refus des `$ref` externes en particulier ne se déplace pas — voir
    son commentaire.
    """
    try:
        data = load_yaml(text, MAX_CONTRACT_BYTES)
    except ModelSyntaxError as exc:
        raise ContractSyntaxError(exc.message, exc.line, exc.column) from None
    if not isinstance(data, dict):
        raise ContractInvalidError([ContractProblem("$", "le document doit être un objet")])
    found = data.get("openapi")
    version = ".".join(str(found).split(".")[:2]) if isinstance(found, str) else None
    if SUPPORTED.get(version or "") is None:
        raise UnsupportedVersionError(str(found) if found is not None else data.get("swagger"))
    # Avant tout : une référence hors du document ferait télécharger au validateur une
    # adresse choisie par l'auteur du fichier, depuis le serveur. Seules les références
    # internes (« #/… ») sont admises — un contrat déposé doit se suffire à lui-même. Une
    # interne qui ne mène nulle part ferait lever le validateur au lieu de la signaler.
    #
    # Reste sur le chemin de LECTURE alors que la validation en sort : c'est une garde de
    # sécurité, elle coûte 4 ms, et un document chargé sans elle serait prêt à faire
    # sortir une requête du serveur dès qu'un appelant le validerait.
    broken = _reference_problems(data)
    if broken:
        raise ContractInvalidError(broken)
    if "info" not in data or not isinstance(data.get("info"), dict):
        # Sans la validation de spécification, c'est ICI qu'un document sans `info.title`
        # se signale : sinon il lèverait un KeyError à la ligne suivante, et l'écran
        # rendrait 500 là où il doit dire « openapi_invalide ».
        raise ContractInvalidError([ContractProblem("$.info", "`info` manquant")])
    title = data["info"].get("title")
    if not isinstance(title, str):
        raise ContractInvalidError([ContractProblem("$.info.title", "`title` manquant")])
    return ParsedContract(title, str(found), tuple(_operations(data)), data)


def parse_contract(text: str) -> ParsedContract:
    """Lit un contrat OpenAPI ET le confronte à la spécification.

    Le geste qui fait ENTRER un contrat — import, aperçu —, et la validation de la
    branche, qui précède le figement d'une version. L'affichage, lui, passe par
    `read_contract` : voir sa docstring pour la décision et la mesure.
    """
    parsed = read_contract(text)
    validator = SUPPORTED[".".join(parsed.openapi.split(".")[:2])]
    problems = [
        ContractProblem(str(error.json_path), error.message)
        for _, error in zip(
            range(MAX_PROBLEMS), validator(parsed.document).iter_errors(), strict=False
        )
    ]
    if problems:
        raise ContractInvalidError(problems)
    return parsed


def _reference_problems(data: dict[str, Any]) -> list[ContractProblem]:
    # Parcours itératif : un document très imbriqué ne doit pas épuiser la pile.
    problems: list[ContractProblem] = []
    stack: list[tuple[Any, str]] = [(data, "$")]
    while stack and len(problems) < MAX_PROBLEMS:
        node, path = stack.pop()
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                problems.append(ContractProblem(path, f"référence externe refusée : {ref}"))
            elif isinstance(ref, str) and not _resolves(data, ref):
                problems.append(ContractProblem(path, f"référence introuvable : {ref}"))
            stack += [(value, f"{path}.{key}") for key, value in node.items()]
        elif isinstance(node, list):
            stack += [(value, f"{path}[{i}]") for i, value in enumerate(node)]
    return sorted(problems, key=lambda p: p.path)


def _resolves(data: Any, ref: str) -> bool:
    """Pointeur JSON (RFC 6901) interne au document."""
    node = data
    for raw in ref.removeprefix("#").split("/")[1:]:
        part = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return False
    return True


def _operations(data: dict[str, Any]) -> list[Operation]:
    # Les webhooks d'un contrat 3.1 sont des opérations comme les autres : un contrat
    # interne ne porte souvent qu'eux.
    operations = []
    for section in ("paths", "webhooks"):
        for route, item in sorted((data.get(section) or {}).items()):
            for method in METHODS:
                operation = item.get(method) if isinstance(item, dict) else None
                if isinstance(operation, dict):
                    operation_id = operation.get("operationId")
                    operations.append(Operation(method, str(route), operation_id))
    return operations
