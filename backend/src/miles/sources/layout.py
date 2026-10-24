from __future__ import annotations

import json
import re
from dataclasses import dataclass

from urban_json.jsonpath import IndexSelector, NameSelector, WildcardSelector

from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.transform.jpath import read_path

# Une source de données (story 66391afe) : COMMENT on remplit un storage, et rien de plus.
#
# Révisé le 24/10/2026 (story 844f15ad) : la source ne porte plus le modèle, la clé ni les
# propriétés filtrables — ils appartiennent au storage, notion distincte décidée par Gael
# le même jour. La source le DÉSIGNE. Raison : un storage s'alimente aussi par API ou par
# MCP, sans source ; et laisser les deux porter le modèle et la clé ferait deux copies,
# qui divergent toujours.
ROOT = "sources"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\.yaml$")
_KEYS = {
    "nom",
    "libelle",
    "storage",
    "decoupage",
    "chaine",
    "mode_gros_fichier",
    "transaction_unifiee",
}


@dataclass(frozen=True)
class SourceDoc:
    # Identifiant : il nomme le fichier, et se déduit du libellé à la création.
    name: str
    # Ce que la personne a écrit, et ce que les écrans affichent.
    label: str
    # Nom du storage alimenté : la collection, son modèle et sa clé vivent là-bas.
    storage: str
    split: str
    chain: str
    large_file: bool
    unified_transaction: bool


@dataclass(frozen=True)
class SourceProblem:
    path: str
    code: str
    detail: str | None = None


def source_path(name: str) -> str:
    return f"{ROOT}/{name}.yaml"


def names_in(paths: list[str]) -> list[str]:
    return sorted(m["name"] for m in map(_FILE_RE.match, paths) if m is not None)


def source_text(doc: SourceDoc) -> str:
    # Valeurs écrites en chaînes JSON, qui sont aussi des chaînes YAML : un jpath porte
    # des « $ », « [ » et « : » qui changeraient la structure du fichier non échappés.
    def q(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    return (
        "\n".join(
            [
                f"nom: {q(doc.name)}",
                f"libelle: {q(doc.label)}",
                f"storage: {q(doc.storage)}",
                f"decoupage: {q(doc.split)}",
                f"chaine: {q(doc.chain)}",
                f"mode_gros_fichier: {'true' if doc.large_file else 'false'}",
                f"transaction_unifiee: {'true' if doc.unified_transaction else 'false'}",
            ]
        )
        + "\n"
    )


def read_source(text: str | None) -> SourceDoc | None:
    """Déclaration lue, ou None si le fichier est absent ou n'en a pas la forme.

    Une source écrite sous l'ancienne forme — `modele`, `cle`, `filtrables` — n'est pas
    reprise en silence : ses clés sont inconnues, donc elle se lit comme illisible, et la
    validation dit quoi faire. Deviner le storage qu'elle visait serait un repli
    silencieux sur un paramétrage qui décide de ce qui est stocké.
    """
    try:
        data = load_yaml(text) if text is not None else None
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - _KEYS:
        return None
    try:
        return SourceDoc(
            _text(data.get("nom")),
            _text(data.get("libelle")),
            _text(data.get("storage")),
            _text(data.get("decoupage")),
            _text(data.get("chaine")),
            _flag(data.get("mode_gros_fichier")),
            _flag(data.get("transaction_unifiee")),
        )
    except (TypeError, AttributeError):
        return None


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def _flag(value: object) -> bool:
    # Absent : faux. Les deux garanties se déclarent ; elles ne s'inventent pas.
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeError
    return value


def form_problems(doc: SourceDoc) -> list[SourceProblem]:
    """Ce qui se vérifie sur la déclaration seule, sans lire la branche."""
    problems = []
    if not NAME_RE.match(doc.name):
        problems.append(SourceProblem("nom", "nom_invalide"))
    if not doc.label.strip():
        problems.append(SourceProblem("libelle", "libelle_vide"))
    if not doc.storage.strip():
        # Sans storage, une source n'a pas de destination : on ne la devine pas.
        problems.append(SourceProblem("storage", "storage_absent"))
    elif not NAME_RE.match(doc.storage):
        problems.append(SourceProblem("storage", "nom_invalide", doc.storage))
    problems += _split_problems(doc.split)
    return problems


def _split_problems(split: str) -> list[SourceProblem]:
    """Le jpath de découpage doit se lire en flux : on ne revient pas en arrière en SAX.

    Admis : des noms ou des indices depuis la racine, puis un seul joker final qui désigne
    les items du tableau. Refusés : un filtre (il faudrait voir l'item entier avant de le
    garder), une descente `..` (non bornée), un joker qui ne termine pas le chemin.
    """
    if not split.strip():
        return [SourceProblem("decoupage", "decoupage_absent")]
    path = read_path(split)
    if path is None:
        return [SourceProblem("decoupage", "jpath_illisible", split)]
    segments = path.compiled.segments
    if not segments:
        return [SourceProblem("decoupage", "non_streamable", "le chemin doit désigner un tableau")]
    for rank, segment in enumerate(segments):
        last = rank == len(segments) - 1
        if segment.is_recursive:
            return [SourceProblem("decoupage", "non_streamable", "descente « .. » non bornée")]
        selector = segment.selectors[0] if len(segment.selectors) == 1 else None
        if last and isinstance(selector, WildcardSelector):
            return []
        if not isinstance(selector, (NameSelector, IndexSelector)):
            reason = "un filtre exige l'item entier avant de le garder"
            if isinstance(selector, WildcardSelector):
                reason = "le joker doit terminer le chemin"
            return [SourceProblem("decoupage", "non_streamable", reason)]
    return [SourceProblem("decoupage", "non_streamable", "le chemin doit finir par [*]")]
