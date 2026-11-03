"""Les filtres du journal d'events, et la FENÊTRE qu'une recherche applique toujours.

Calcul PUR : il prend des filtres et rend du SQL et des paramètres. Une erreur ici fait
rendre les mauvais events, ou fait traverser tout le journal — deux choses qu'on veut
éprouver sans base.

**Pourquoi une fenêtre par défaut, et non « tout ».** `written_at` est la clé de partition
depuis l'enabler `8e86afbc` : une requête sans borne de date doit considérer TOUTES les
partitions, et le journal est fait pour grossir jusqu'à sa rétention. Le défaut est donc une
fenêtre récente, et la réponse DIT laquelle — un écran qui montre sept jours en laissant
croire qu'il montre tout est pire qu'un écran vide.

**Ce qui n'est pas ici** : le filtrage sur le contenu de `properties`. Rien ne déclare quelles
clefs d'un type d'event sont filtrables, et où cette déclaration doit vivre est une décision
d'architecture non tranchée (ticket 461f0cf1). Les `properties` sont donc AFFICHÉES et jamais
interrogées — y compris « juste pour la source ».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# Sept jours : assez pour répondre à « qu'est-ce qui s'est passé cette semaine », assez
# court pour que la requête ne lise qu'une poignée de partitions.
DEFAULT_WINDOW = timedelta(days=7)
PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

REFUSAL_WINDOW = "bornes_inversees"
REFUSAL_AUTHOR = "auteur_incomplet"
REFUSAL_OBJECT = "objet_incomplet"
REFUSAL_PAGE = "page_invalide"


class SearchRefusal(Exception):
    """Un filtre inutilisable. Nommé, jamais appliqué à moitié."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class EventFilter:
    type: str | None = None
    # Les deux moitiés de l'identité, exigées ENSEMBLE : filtrer sur le seul annuaire
    # rendrait tous les events de tous ses comptes, ce que personne ne demande en
    # écrivant « auteur ».
    author_directory: str | None = None
    author_subject: str | None = None
    object_kind: str | None = None
    object_id: str | None = None
    written_from: datetime | None = None
    written_to: datetime | None = None
    # Distincte de la date d'écriture, et c'est tout l'intérêt de les séparer : une
    # confirmation tardive ou un import rejoué portent une date métier antérieure.
    functional_from: datetime | None = None
    functional_to: datetime | None = None


@dataclass(frozen=True)
class Window:
    """La fenêtre d'écriture réellement appliquée, et si l'appelant l'a demandée."""

    start: datetime
    end: datetime
    defaulted: bool


def resolve_window(filtre: EventFilter, now: datetime) -> Window:
    debut = filtre.written_from or now - DEFAULT_WINDOW
    fin = filtre.written_to or now
    if debut > fin:
        raise SearchRefusal(REFUSAL_WINDOW, f"written_at : {debut.isoformat()} > {fin.isoformat()}")
    if filtre.functional_from and filtre.functional_to:
        if filtre.functional_from > filtre.functional_to:
            raise SearchRefusal(
                REFUSAL_WINDOW,
                f"functional_at : {filtre.functional_from.isoformat()}"
                f" > {filtre.functional_to.isoformat()}",
            )
    return Window(debut, fin, filtre.written_from is None and filtre.written_to is None)


def checked_page(page: int, size: int) -> tuple[int, int]:
    """Le rang et la taille, bornés. Une taille non bornée est une fuite de mémoire."""
    if page < 1:
        raise SearchRefusal(REFUSAL_PAGE, f"page {page} : la première est 1")
    if size < 1 or size > MAX_PAGE_SIZE:
        raise SearchRefusal(REFUSAL_PAGE, f"taille {size} : entre 1 et {MAX_PAGE_SIZE}")
    return page, size


def conditions(filtre: EventFilter, window: Window) -> tuple[str, list[Any]]:
    """Le `WHERE` et ses paramètres. La borne d'écriture y est TOUJOURS, en premier.

    Paramétré, jamais concaténé : les valeurs viennent d'une requête HTTP.
    """
    # Les deux bornes sont INCLUSIVES, à la différence des bornes de partition qui sont
    # mi-ouvertes. Mesuré le 03/11/2026 : avec `<`, un event écrit à l'instant même où
    # l'horloge de la recherche a été lue disparaissait de sa propre fenêtre — le plus
    # récent, c'est-à-dire celui qu'on cherche. Et « jusqu'au 3 novembre » veut dire
    # « le 3 novembre compris » pour quiconque le tape.
    clauses = ["e.written_at >= $1", "e.written_at <= $2"]
    valeurs: list[Any] = [window.start, window.end]

    def ajoute(clause: str, *args: Any) -> None:
        rangs = tuple(len(valeurs) + n + 1 for n in range(len(args)))
        clauses.append(clause.format(*(f"${r}" for r in rangs)))
        valeurs.extend(args)

    if filtre.type is not None:
        ajoute("e.type = {0}", filtre.type)
    annuaire, sujet = filtre.author_directory, filtre.author_subject
    if (annuaire is None) != (sujet is None):
        raise SearchRefusal(REFUSAL_AUTHOR, "author_directory et author_subject vont ensemble")
    if annuaire is not None and sujet is not None:
        ajoute("e.author_directory = {0} AND e.author_subject = {1}", annuaire, sujet)
    genre, identifiant = filtre.object_kind, filtre.object_id
    if (genre is None) != (identifiant is None):
        raise SearchRefusal(REFUSAL_OBJECT, "object_kind et object_id vont ensemble")
    if genre is not None and identifiant is not None:
        # `written_at` dans la jointure : c'est la clé de partition des deux tables, et
        # sans elle le planificateur parcourt toutes les partitions des liens.
        ajoute(
            "EXISTS (SELECT 1 FROM event_objects o WHERE o.event_id = e.id"
            " AND o.written_at = e.written_at AND o.object_kind = {0} AND o.object_id = {1})",
            genre,
            identifiant,
        )
    if filtre.functional_from is not None:
        ajoute("e.functional_at >= {0}", filtre.functional_from)
    if filtre.functional_to is not None:
        ajoute("e.functional_at <= {0}", filtre.functional_to)
    return " AND ".join(clauses), valeurs


def missing_in_range(present: list[int]) -> list[int]:
    """Les numéros de séquence absents ENTRE le plus petit et le plus grand rendus.

    Et non « depuis 1 », à la différence de `db_object_history` : ici la recherche est
    bornée dans le temps, et la purge de rétention efface les premiers events par
    construction. Réclamer le numéro 1 signalerait un trou à chaque fois, donc ne
    signalerait plus rien. Un trou À L'INTÉRIEUR de l'intervalle observé, en revanche, est
    une vraie histoire incomplète.
    """
    if len(present) < 2:
        return []
    return sorted(set(range(min(present), max(present) + 1)) - set(present))
