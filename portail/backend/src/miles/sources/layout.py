"""Ce que le module de paramétrage fait d'une déclaration de source : l'ÉCRIRE et la
DIAGNOSTIQUER.

La grammaire et la LECTURE sont au socle depuis le 02/11/2026 (`miles_socle.parametrage.sources`),
deuxième usage : le module d'environnement lit les mêmes fichiers dans la version qu'il
héberge, pour savoir quels points d'entrée exposer et quelles sources une clé d'API peut
ouvrir. Elles sont réexportées ici sous leurs noms d'origine — les appelants du portail
n'ont pas à savoir qu'elles ont déménagé.

Ce qui RESTE ici, et pourquoi : l'écriture suppose la forme exacte du fichier qu'on
produit, et le diagnostic suppose le registre des modèles de la branche et le parseur de
jpath du moteur. Un consommateur n'a que faire de l'un ni de l'autre : il lit un fichier
déjà écrit, et un refus se rend à qui édite, pas à qui consomme.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from miles_socle.parametrage.sources import (
    DEFAULT_WRITE_BATCH,
    ENTRY_TYPES,
    MAX_BATCH,
    NAME_RE,
    ROOT,
    WEB,
    Entry,
    EntryModes,
    SourceDoc,
    names_in,
    read_source,
    source_path,
)
from miles_socle.transform.jpath import SplitRefusal, read_stream_split

from miles.datamodels.layout import MODEL_RE

__all__ = [
    "DEFAULT_WRITE_BATCH",
    "ENTRY_TYPES",
    "MAX_BATCH",
    "NAME_RE",
    "ROOT",
    "WEB",
    "Entry",
    "EntryModes",
    "SourceDoc",
    "SourceProblem",
    "form_problems",
    "names_in",
    "read_source",
    "source_path",
    "source_text",
]


@dataclass(frozen=True)
class SourceProblem:
    path: str
    code: str
    detail: str | None = None


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
            f"    lot_ecriture: {entry.write_batch}",
        ]
    return "\n".join(lines) + "\n"


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
    if entry.write_batch < 1:
        # Zéro lecture avant enregistrement n'enregistrerait jamais rien.
        problems.append(
            SourceProblem(f"{where}.lot_ecriture", "lot_trop_petit", str(entry.write_batch))
        )
    problems += _split_problems(where, entry.split, modes.file)
    return problems


def _split_problems(where: str, split: str, needed: bool) -> list[SourceProblem]:
    """Le jpath de découpage doit se lire en flux : on ne revient pas en arrière en SAX.

    **La règle est au socle** (`read_stream_split`) depuis le 04/11/2026, deuxième usage :
    le module d'environnement en dérive le chemin des items pour lire le document, et une
    seconde copie de la règle aurait fini par accepter ici ce qu'il refuse là. Ce qui reste
    ICI est ce qui n'a de sens qu'à la saisie : l'EXIGENCE du découpage, qui dépend du mode
    coché, et la mise en forme du refus pour l'écran qui édite.

    Exigé par le seul mode fichier : c'est le seul où l'on reçoit un DOCUMENT et où il
    faut dire où sont les items. Hors de ce mode il est admis vide, et vérifié s'il est là.
    """
    field = f"{where}.decoupage"
    if not split.strip():
        return [SourceProblem(field, "decoupage_absent")] if needed else []
    lu = read_stream_split(split)
    if isinstance(lu, SplitRefusal):
        return [SourceProblem(field, lu.code, lu.detail)]
    return []
