from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
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


def parse_contract(text: str) -> ParsedContract:
    """Lit et vérifie un contrat OpenAPI, en YAML ou en JSON (le JSON est du YAML)."""
    try:
        data = load_yaml(text, MAX_CONTRACT_BYTES)
    except ModelSyntaxError as exc:
        raise ContractSyntaxError(exc.message, exc.line, exc.column) from None
    if not isinstance(data, dict):
        raise ContractInvalidError([ContractProblem("$", "le document doit être un objet")])
    found = data.get("openapi")
    version = ".".join(str(found).split(".")[:2]) if isinstance(found, str) else None
    validator = SUPPORTED.get(version or "")
    if validator is None:
        raise UnsupportedVersionError(str(found) if found is not None else data.get("swagger"))
    # Avant tout : une référence hors du document ferait télécharger au validateur une
    # adresse choisie par l'auteur du fichier, depuis le serveur. Seules les références
    # internes (« #/… ») sont admises — un contrat déposé doit se suffire à lui-même. Une
    # interne qui ne mène nulle part ferait lever le validateur au lieu de la signaler.
    broken = _reference_problems(data)
    if broken:
        raise ContractInvalidError(broken)
    problems = [
        ContractProblem(str(error.json_path), error.message)
        for _, error in zip(range(MAX_PROBLEMS), validator(data).iter_errors(), strict=False)
    ]
    if problems:
        raise ContractInvalidError(problems)
    return ParsedContract(str(data["info"]["title"]), str(found), tuple(_operations(data)))


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
    # entrant ne porte souvent qu'eux.
    operations = []
    for section in ("paths", "webhooks"):
        for route, item in sorted((data.get(section) or {}).items()):
            for method in METHODS:
                operation = item.get(method) if isinstance(item, dict) else None
                if isinstance(operation, dict):
                    operation_id = operation.get("operationId")
                    operations.append(Operation(method, str(route), operation_id))
    return operations


def propose_slug(title: str) -> str:
    """Slug proposé depuis le titre : minuscules sans accents, mots séparés par des tirets.

    Rend une chaîne vide quand rien ne reste après normalisation : c'est alors à
    l'utilisateur de donner un slug explicite (critère 5), on n'en invente pas.
    """
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")
    return slug[:63].rstrip("-")
