from __future__ import annotations

import json
import re
from dataclasses import dataclass

from urban_json.jsonpath import IndexSelector, NameSelector, WildcardSelector

from miles.datamodels.grammar import ModelSyntaxError, load_yaml
from miles.datamodels.layout import MODEL_RE
from miles.transform.jpath import read_path

# Une source de données (story 66391afe, refondue le 25/10/2026) : une ENTRÉE de données
# dans l'application. Elle dit d'abord OÙ ça va — la donnée cible, c'est-à-dire le storage
# — et c'est tout ce qu'il faut pour l'enregistrer. Elle porte ensuite une ou plusieurs
# entrées, chacune décrivant par quel moyen la donnée arrive.
#
# Un fichier par source, à la racine comme les storages et les chaînes.
ROOT = "sources"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\.yaml$")
_KEYS = {"nom", "libelle", "storage", "entrees"}
_ENTRY_KEYS = {"type", "modele_source", "chaine", "modes", "decoupage", "transaction_unifiee"}
_MODE_KEYS = {"element", "tableau", "fichier"}

# Le seul moyen d'entrée instruit à ce jour. Le type est écrit dans la déclaration plutôt
# que sous-entendu : un second moyen (fichier déposé, file de messages) s'ajoutera sans
# rendre ambiguës les déclarations déjà écrites.
WEB = "web"
ENTRY_TYPES = frozenset({WEB})
# Plafond du mode tableau (Gael, 25/10/2026). C'est une décision, pas une limite
# technique : au-delà, un appel unique devient un lot qu'il faut reprendre et suivre,
# et c'est le mode fichier qui le sert.
MAX_BATCH = 200


@dataclass(frozen=True)
class EntryModes:
    """Les méthodes exposées par une entrée. Au moins une, sinon elle n'expose rien."""

    # Un objet du modèle source, pour les intégrations à l'unité.
    element: bool
    # Un tableau d'objets du modèle source, MAX_BATCH au plus.
    batch: bool
    # Un fichier déposé, rangé en répertoire temporaire puis lu en flux (SAX) selon le
    # jpath de découpage — d'où l'exigence de ce découpage dès que ce mode est coché.
    file: bool


@dataclass(frozen=True)
class Entry:
    kind: str
    # « portée/nom » du modèle qui arrive sur la méthode.
    source_model: str
    # Slug de la chaîne qui mène du modèle source au modèle du storage.
    chain: str
    modes: EntryModes
    # Où sont les items dans le fichier déposé. Requis par le mode fichier, et par lui
    # seul : les deux autres méthodes reçoivent déjà des objets typés.
    split: str
    unified_transaction: bool


@dataclass(frozen=True)
class SourceDoc:
    # Identifiant : il nomme le fichier, et se déduit du libellé à la création.
    name: str
    # Ce que la personne a écrit, et ce que les écrans affichent.
    label: str
    # La donnée cible : le storage où les objets atterrissent.
    storage: str
    entries: tuple[Entry, ...]


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

    def flag(value: bool) -> str:
        return "true" if value else "false"

    lines = [
        f"nom: {q(doc.name)}",
        f"libelle: {q(doc.label)}",
        f"storage: {q(doc.storage)}",
    ]
    if not doc.entries:
        lines.append("entrees: []")
        return "\n".join(lines) + "\n"
    lines.append("entrees:")
    for entry in doc.entries:
        lines += [
            f"  - type: {q(entry.kind)}",
            f"    modele_source: {q(entry.source_model)}",
            f"    chaine: {q(entry.chain)}",
            "    modes:",
            f"      element: {flag(entry.modes.element)}",
            f"      tableau: {flag(entry.modes.batch)}",
            f"      fichier: {flag(entry.modes.file)}",
            f"    decoupage: {q(entry.split)}",
            f"    transaction_unifiee: {flag(entry.unified_transaction)}",
        ]
    return "\n".join(lines) + "\n"


def read_source(text: str | None) -> SourceDoc | None:
    """Déclaration lue, ou None si le fichier est absent ou n'en a pas la forme."""
    try:
        data = load_yaml(text) if text is not None else None
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - _KEYS:
        return None
    raw = data.get("entrees")
    if raw is not None and not isinstance(raw, list):
        return None
    try:
        return SourceDoc(
            _text(data.get("nom")),
            _text(data.get("libelle")),
            _text(data.get("storage")),
            tuple(_entry(e) for e in (raw or [])),
        )
    except (TypeError, AttributeError):
        return None


def _entry(raw: object) -> Entry:
    if not isinstance(raw, dict) or set(map(str, raw)) - _ENTRY_KEYS:
        raise TypeError
    modes = raw.get("modes")
    if not isinstance(modes, dict) or set(map(str, modes)) - _MODE_KEYS:
        raise TypeError
    return Entry(
        _text(raw.get("type")),
        _text(raw.get("modele_source")),
        _text(raw.get("chaine")),
        EntryModes(
            _flag(modes.get("element")), _flag(modes.get("tableau")), _flag(modes.get("fichier"))
        ),
        _text(raw.get("decoupage")),
        _flag(raw.get("transaction_unifiee")),
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def _flag(value: object) -> bool:
    # Absent : faux. Un mode et une garantie se déclarent ; ils ne s'inventent pas.
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
        # Sans donnée cible, une source n'a pas de destination : on ne la devine pas.
        problems.append(SourceProblem("storage", "storage_absent"))
    elif not NAME_RE.match(doc.storage):
        problems.append(SourceProblem("storage", "nom_invalide", doc.storage))
    for rank, entry in enumerate(doc.entries):
        problems += _entry_problems(rank, entry)
    return problems


def _entry_problems(rank: int, entry: Entry) -> list[SourceProblem]:
    where = f"entrees[{rank}]"
    problems = []
    if entry.kind not in ENTRY_TYPES:
        problems.append(SourceProblem(f"{where}.type", "type_inconnu", entry.kind))
    if not MODEL_RE.match(entry.source_model):
        problems.append(
            SourceProblem(f"{where}.modele_source", "modele_invalide", entry.source_model)
        )
    if not entry.chain.strip():
        problems.append(SourceProblem(f"{where}.chaine", "chaine_absente"))
    modes = entry.modes
    if not (modes.element or modes.batch or modes.file):
        # Une entrée sans mode n'expose aucune méthode : elle ne reçoit rien.
        problems.append(SourceProblem(f"{where}.modes", "aucun_mode"))
    problems += _split_problems(where, entry.split, modes.file)
    return problems


def _split_problems(where: str, split: str, needed: bool) -> list[SourceProblem]:
    """Le jpath de découpage doit se lire en flux : on ne revient pas en arrière en SAX.

    Admis : des noms ou des indices depuis la racine, puis un seul joker final qui désigne
    les items du tableau. Refusés : un filtre (il faudrait voir l'item entier avant de le
    garder), une descente `..` (non bornée), un joker qui ne termine pas le chemin.

    Exigé par le seul mode fichier : c'est le seul où l'on reçoit un DOCUMENT et où il
    faut dire où sont les items. Hors de ce mode il est admis vide, et vérifié s'il est là.
    """
    field = f"{where}.decoupage"
    if not split.strip():
        return [SourceProblem(field, "decoupage_absent")] if needed else []
    path = read_path(split)
    if path is None:
        return [SourceProblem(field, "jpath_illisible", split)]
    segments = path.compiled.segments
    if not segments:
        return [SourceProblem(field, "non_streamable", "le chemin doit désigner un tableau")]
    for rank, segment in enumerate(segments):
        last = rank == len(segments) - 1
        if segment.is_recursive:
            return [SourceProblem(field, "non_streamable", "descente « .. » non bornée")]
        selector = segment.selectors[0] if len(segment.selectors) == 1 else None
        if last and isinstance(selector, WildcardSelector):
            return []
        if not isinstance(selector, (NameSelector, IndexSelector)):
            reason = "un filtre exige l'item entier avant de le garder"
            if isinstance(selector, WildcardSelector):
                reason = "le joker doit terminer le chemin"
            return [SourceProblem(field, "non_streamable", reason)]
    return [SourceProblem(field, "non_streamable", "le chemin doit finir par [*]")]
