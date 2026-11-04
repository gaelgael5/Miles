from __future__ import annotations

import json
import re
from dataclasses import dataclass

from miles.contracts.openapi import SLUG_RE
from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.workspaces.model import WorkspaceInputError

# Externe : appel d'un service distant ; interne : webhook reçu. Pas de valeur par
# défaut : un webhook pris pour un appel externe produirait un mapping à l'envers.
DIRECTIONS = frozenset({"externe", "interne"})
# Ces valeurs se nommaient « sortant » et « entrant » jusqu'au 23/10/2026 (Gael) : le
# vocabulaire métier est externe/interne, jusque dans la donnée stockée. Les déclarations
# déjà commitées dans les dépôts de paramétrage, eux hors de Miles, portent encore les
# anciennes ; elles sont acceptées EN LECTURE SEULE parce que read_meta rend None sur un
# sens inconnu — un contrat existant disparaîtrait de l'écran sans message plutôt que
# d'échouer bruyamment. Toute écriture repose la valeur canonique, donc un contrat migre
# à sa première modification. À retirer quand plus aucun dépôt de paramétrage ne porte
# l'ancien vocabulaire. La correspondance ne va que dans ce sens : un retour arrière de
# Miles après migration demande de revenir aussi sur les commits de paramétrage, sinon
# l'ancienne version ne lira plus « externe » et fera disparaître le contrat.
_LEGACY_DIRECTIONS = {"sortant": "externe", "entrant": "interne"}
META = "contract.yaml"
VERSION_RE = re.compile(r"^v(?P<number>[1-9]\d{0,5})\.yaml$")
_FILE_RE = re.compile(r"^contracts/(?P<slug>[^/]+)/(?P<file>[^/]+)$")


@dataclass(frozen=True)
class VersionImport:
    """Dépôt d'une version de contrat : quand, et par qui (story b2305542)."""

    # ISO 8601. Tenu dans git avec le contrat : le journal d'events, lui, se purge.
    imported_at: str
    by: str


@dataclass(frozen=True)
class ContractMeta:
    slug: str
    label: str
    direction: str
    # Par numéro de version. Absent : version déposée hors de Miles, sans date connue.
    imports: tuple[tuple[int, VersionImport], ...] = ()

    def declaration(self) -> tuple[str, str, str]:
        """Ce que fige la déclaration ; les dépôts de versions n'en font pas partie."""
        return self.slug, self.label, self.direction

    def imported(self, number: int) -> VersionImport | None:
        return dict(self.imports).get(number)

    def with_import(self, number: int, entry: VersionImport) -> ContractMeta:
        imports = dict(self.imports) | {number: entry}
        return ContractMeta(self.slug, self.label, self.direction, tuple(sorted(imports.items())))


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
    # Le type se vérifie AVANT toute correspondance : un sens non textuel (« sens: [x] »,
    # écrit par une retouche hors de Miles) n'est pas hachable, et ferait lever aussi bien
    # le .get() ci-dessous que le test d'appartenance à DIRECTIONS. Un TypeError n'est pas
    # un refus connu : il rendrait 500 sur tout l'écran des contrats et sur la validation
    # de branche, là où un fichier malformé doit seulement être déclaré illisible.
    if not isinstance(slug, str) or not isinstance(direction, str):
        return None
    direction = _LEGACY_DIRECTIONS.get(direction, direction)
    if direction not in DIRECTIONS:
        return None
    # Repli volontaire : les contrats importés avant la déclaration explicite (22/10/2026)
    # n'ont pas de label. Leur slug en tient lieu plutôt que de les rendre invalides.
    if label is None:
        label = slug
    if not isinstance(label, str):
        return None
    imports = _imports(data.get("versions"))
    if imports is None:
        return None
    return ContractMeta(slug, label, str(direction), imports)


def _imports(raw: object) -> tuple[tuple[int, VersionImport], ...] | None:
    """Dépôts lus dans la déclaration ; None si la section est mal formée."""
    if raw is None:
        return ()
    if not isinstance(raw, dict):
        return None
    entries = []
    for number, entry in raw.items():
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            return None
        if not isinstance(entry, dict):
            return None
        at, by = entry.get("imported_at"), entry.get("by")
        if not isinstance(at, str) or not isinstance(by, str):
            return None
        entries.append((number, VersionImport(at, by)))
    return tuple(sorted(entries))


def meta_text(meta: ContractMeta) -> str:
    # Le label est libre : écrit en chaîne JSON, qui est aussi une chaîne YAML entre
    # guillemets, pour qu'aucun « : » ni « # » saisi ne change la structure du fichier.
    label = json.dumps(meta.label, ensure_ascii=False)
    text = f"slug: {meta.slug}\nlabel: {label}\nsens: {meta.direction}\n"
    if meta.imports:
        text += "versions:\n"
        for number, entry in meta.imports:
            # Mêmes guillemets JSON : l'auteur porte « < > » et la date des « : ».
            at = json.dumps(entry.imported_at)
            by = json.dumps(entry.by, ensure_ascii=False)
            text += f"  {number}:\n    imported_at: {at}\n    by: {by}\n"
    return text


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
