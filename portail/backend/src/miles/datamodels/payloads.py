"""Le payload d'un type d'event ne se désigne pas comme un modèle d'objet.

Décidé le 22/11/2026 (story `7b4f7a32`, feature `c8f3d8da`, décision 3), après Gael le
19/11 : « les events apparaissent dans le menu events mais pas dans le menu model ». Un
modèle qu'un `DEFINE EVENT` nomme décrit un FAIT qui entre par le journal ; un storage le
projetterait en objet et une source l'ingérerait comme une donnée du référentiel — deux
gestes qui n'ont pas de sens sur un fait, et dont rien ne disait qu'ils étaient refusés.

Le déclencheur est l'USAGE du modèle, jamais son nom ni son dossier : depuis le
14/11/2026, « ce qui fait d'un modèle un type d'event, c'est qu'un `DEFINE EVENT` le
nomme, et rien d'autre ». Conséquence voulue : un modèle qui CESSE d'être un payload — sa
déclaration supprimée — redevient désignable, sans migration et sans fichier à retoucher.

**Ce module sert le GESTE, pas le figement.** Arbitré par Gael le 22/11/2026 : une
désignation DÉJÀ posée est signalée, et la version se fige quand même — « signalées,
jamais cassées en silence ». C'est pourquoi `storage_reports` et `source_reports`
n'appellent pas d'ici, alors qu'ils rejouent par ailleurs toutes les règles de
l'écriture : une branche qu'on livrait hier doit pouvoir se livrer aujourd'hui.
"""

from __future__ import annotations

from collections.abc import Sequence

from miles_socle.parametrage.layout import MODEL_RE

from miles.datamodels.usages import Reader, read_event_designations

# Le refus, nommé une seule fois pour les deux appelants : le storage et la source le
# rendent chacun dans SON type de manquement, mais c'est la même règle, et deux codes
# auraient demandé deux libellés pour une seule chose à comprendre.
PAYLOAD = "modele_de_payload"


async def event_payloads(read: Reader, paths: Sequence[str]) -> dict[tuple[str, str], str]:
    """Chaque modèle qu'un `DEFINE EVENT` nomme, et « <type d'event> · <artefact> ».

    Une passe pour toute la branche, et non une par champ à vérifier : une source porte
    plusieurs entrées, et relire les artefacts pour chacune aurait fait payer au geste
    autant de parcours que d'entrées.

    La valeur NOMME le type d'event fautif, au lieu de dire seulement qu'il en existe un :
    sans son nom et son artefact, le refus laisserait chercher dans tous les périmètres
    lequel prend ce modèle pour payload.
    """
    found: dict[tuple[str, str], str] = {}
    for designation in await read_event_designations(read, list(paths)):
        # Le premier qui le prend. Rien n'interdit à deux types d'event de partager un
        # payload — seul le NOM d'un type est unique (`nom_declare_deux_fois`) — mais le
        # refus n'a qu'un endroit à montrer pour qu'on sache où aller le retirer.
        found.setdefault(designation.target, f"{designation.name} · {designation.path}")
    return found


def claimed(payloads: dict[tuple[str, str], str], model: str) -> str | None:
    """Le type d'event qui prend `model` (« portée/nom ») pour payload ; None s'il est libre."""
    match = MODEL_RE.match(model)
    if match is None:
        # Le champ ne désigne même pas un modèle : son propre refus le dit déjà
        # (`modele_inconnu`), et en ajouter un deuxième enverrait corriger deux fois.
        return None
    return payloads.get((match["scope"], match["name"]))
