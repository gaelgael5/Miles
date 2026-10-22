from __future__ import annotations

import json
import re
from dataclasses import dataclass

from miles.contracts.openapi import SLUG_RE
from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.workspaces.model import WorkspaceInputError

# Sortant : appel d'un service distant ; entrant : webhook reçu. Pas de valeur par
# défaut : un webhook pris pour un appel sortant produirait un mapping à l'envers.
DIRECTIONS = frozenset({"sortant", "entrant"})
META = "contract.yaml"
VERSION_RE = re.compile(r"^v(?P<number>[1-9]\d{0,5})\.yaml$")
_FILE_RE = re.compile(r"^contracts/(?P<slug>[^/]+)/(?P<file>[^/]+)$")


@dataclass(frozen=True)
class ContractMeta:
    slug: str
    label: str
    direction: str


def contract_dir(slug: str) -> str:
    return f"contracts/{slug}"


def meta_path(slug: str) -> str:
    return f"{contract_dir(slug)}/{META}"


def version_path(slug: str, number: int) -> str:
    return f"{contract_dir(slug)}/v{number}.yaml"


def read_meta(text: str | None) -> ContractMeta | None:
    """Déclaration du contrat, ou None si elle est absente ou illisible."""
    try:
        data = load_yaml(text) if text is not None else None
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict):
        return None
    slug, label, direction = data.get("slug"), data.get("label"), data.get("sens")
    if not isinstance(slug, str) or direction not in DIRECTIONS:
        return None
    # Repli volontaire : les contrats importés avant la déclaration explicite (22/10/2026)
    # n'ont pas de label. Leur slug en tient lieu plutôt que de les rendre invalides.
    if label is None:
        label = slug
    if not isinstance(label, str):
        return None
    return ContractMeta(slug, label, str(direction))


def meta_text(meta: ContractMeta) -> str:
    # Le label est libre : écrit en chaîne JSON, qui est aussi une chaîne YAML entre
    # guillemets, pour qu'aucun « : » ni « # » saisi ne change la structure du fichier.
    label = json.dumps(meta.label, ensure_ascii=False)
    return f"slug: {meta.slug}\nlabel: {label}\nsens: {meta.direction}\n"


def slugs_in(paths: list[str]) -> list[str]:
    return sorted(
        m["slug"] for m in map(_FILE_RE.match, paths) if m is not None and m["file"] == META
    )


def versions_in(paths: list[str], slug: str) -> list[int]:
    """Numéros des versions de contrat présentes, croissants : elles coexistent (cadrage)."""
    numbers = []
    for path in paths:
        match = _FILE_RE.match(path)
        if match is not None and match["slug"] == slug:
            version = VERSION_RE.match(match["file"])
            if version is not None:
                numbers.append(int(version["number"]))
    return sorted(numbers)


def checked_slug(slug: str) -> str:
    # Vide : la normalisation du label n'a rien laissé, on demande un slug explicite
    # plutôt que d'en inventer un.
    slug = slug.strip()
    if not slug:
        raise WorkspaceInputError("slug", "vide")
    if not SLUG_RE.match(slug):
        raise WorkspaceInputError("slug")
    return slug
