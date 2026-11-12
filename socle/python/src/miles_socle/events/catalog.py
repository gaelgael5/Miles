"""Le catalogue des types d'event déclarés par le code, et la validation de leur bloc.

Décision du 18 octobre 2026, répartie par l'amendement du 26 : le module de paramétrage et
le module d'enrôlement déclarent leurs types **avec leur code** — leurs events ne dépendent
d'aucun paramétrage, donc le catalogue en code est pour eux la bonne réponse et non une
dette. Seul le module d'environnement lit le sien dans le dépôt du workspace.

Chaque type déclare quatre choses, et **aucune n'a de valeur par défaut** : un identifiant,
un libellé, sa catégorie (qui introduit l'event, donc qui peut l'éditer) et le **schéma de
son bloc de propriétés**. Sans le bloc décrit, « catalogue » ne voudrait rien dire de plus
qu'une liste de noms — et c'est l'état qu'on quitte, constaté le 3 novembre 2026.

**Ce qui est refusé AU CHARGEMENT, et non au premier event** : un doublon d'identifiant, une
déclaration qui redéclare un champ de la racine commune, un schéma de bloc qui n'est pas un
objet. Le refus au chargement fait tomber le démarrage du produit, ce qui est le bon moment
pour apprendre qu'un catalogue est faux ; le refus au premier event ferait tomber un geste
métier choisi au hasard par le trafic.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from miles_socle.events.categories import EventCategory
from miles_socle.events.model import NAME_RE, EventError, NewEvent
from miles_socle.events.root import ROOT_FIELDS


class CatalogError(ValueError):
    """Catalogue invalide : refus au chargement, en nommant ce qui ne va pas."""


# Ce que le JOURNAL ajoute lui-même au bloc, et qu'aucun producteur n'écrit : la clé par
# laquelle une modification est passée, quand l'auteur agit par une clé d'API ou un octroi
# OAuth (`events.journal._properties`). Mesuré le 12/11/2026, et c'est ce qui aurait
# invalidé toutes les déclarations d'un coup : un bloc fermé par son auteur aurait refusé
# TOUS les events écrits par la surface MCP, sans rapport avec ce que le type déclare.
# Les déclarer ici une fois laisse chaque type libre de fermer son bloc.
JOURNAL_ADDED: Mapping[str, Any] = {
    "via_api_key": {"type": "string"},
    "via_oauth_grant": {"type": "string"},
}


@dataclass(frozen=True)
class EventShape:
    """Un type d'event tel que le MODULE qui le produit le déclare : sans sa catégorie.

    Pourquoi la catégorie n'est pas ici, mesuré le 12/11/2026 : les modules du socle —
    cultures, OIDC, secrets, identité de module — sont produits par **les trois produits**,
    et la catégorie dit lequel les introduit. `culture.activated` est donc
    `backoffice-configuration` au portail et `backoffice-enrolement` à l'enrôlement, pour
    une seule déclaration. La fixer dans le module aurait obligé à trois déclarations du
    même type, qui auraient divergé au premier changement de libellé.
    """

    name: str
    label: str
    block: Mapping[str, Any]


@dataclass(frozen=True)
class DeclaredEvent:
    """Un type d'event déclaré par le code qui le produit.

    `block` est le JSON Schema du **bloc de propriétés**, pas celui de l'event entier : la
    racine commune vit en colonnes du journal, et un type qui la redéclarerait serait
    refusé (voir `_checked`).
    """

    name: str
    label: str
    category: EventCategory
    block: Mapping[str, Any]


def introduced_by(
    category: EventCategory, *groups: Iterable[EventShape]
) -> tuple[DeclaredEvent, ...]:
    """Les types de ces modules, introduits par ce produit-ci.

    C'est le produit qui pose la catégorie, parce que c'est lui qui introduit l'event —
    voir `EventShape`. Un même module du socle passe donc par ici dans les trois produits,
    avec trois catégories et une seule déclaration.
    """
    return tuple(
        DeclaredEvent(shape.name, shape.label, category, shape.block)
        for group in groups
        for shape in group
    )


def _checked(declared: DeclaredEvent) -> None:
    if not NAME_RE.match(declared.name):
        raise CatalogError(f"identifiant de type d'event invalide : {declared.name!r}")
    if not declared.label.strip():
        raise CatalogError(f"type d'event sans libellé : {declared.name!r}")
    if declared.block.get("type") != "object":
        # Un bloc de propriétés est un objet. Un schéma de tableau ou de scalaire ferait
        # valider l'event contre autre chose que ce que le journal stocke.
        raise CatalogError(f"le bloc de {declared.name!r} n'est pas un schéma d'objet")
    heurte = sorted(set(declared.block.get("properties") or {}) & ROOT_FIELDS)
    if heurte:
        # La racine est portée par les colonnes. Un type qui la redéclare créerait une
        # seconde valeur pour le même champ, et deux producteurs la nommeraient autrement.
        raise CatalogError(
            f"le bloc de {declared.name!r} redéclare un champ de la racine : {heurte}"
        )
    try:
        Draft202012Validator.check_schema(dict(declared.block))
    except SchemaError as erreur:
        raise CatalogError(
            f"schéma de bloc invalide pour {declared.name!r} : {erreur.message}"
        ) from erreur


def _validated(block: Mapping[str, Any]) -> dict[str, Any]:
    """Le schéma contre lequel un bloc est validé : celui du type, plus ce que le journal
    ajoute. Les propriétés du type l'emportent, pour qu'un type qui aurait son avis sur
    `via_api_key` garde le sien."""
    schema = dict(block)
    declarees = block.get("properties")
    if declarees is not None:
        schema["properties"] = {**JOURNAL_ADDED, **declarees}
    return schema


class EventCatalog:
    """Les types admis, avec de quoi valider le bloc de chacun. Un inconnu est rejeté."""

    def __init__(self, declared: Iterable[DeclaredEvent] = ()) -> None:
        self._types: dict[str, DeclaredEvent] = {}
        self._validators: dict[str, Draft202012Validator] = {}
        for item in declared:
            _checked(item)
            if item.name in self._types:
                raise CatalogError(f"type d'event déclaré deux fois : {item.name!r}")
            self._types[item.name] = item
            self._validators[item.name] = Draft202012Validator(_validated(item.block))

    def names(self) -> frozenset[str]:
        return frozenset(self._types)

    def of(self, name: str) -> DeclaredEvent:
        try:
            return self._types[name]
        except KeyError:
            raise EventError(f"type d'event inconnu du catalogue : {name!r}") from None

    def check_event(self, event: NewEvent) -> None:
        """Le type est-il déclaré, et son bloc conforme ?

        **Le refus NOMME la propriété fautive** et non « schéma invalide » : c'est la
        différence entre un refus qu'on corrige et un refus qu'on va relire dans les
        journaux. Le premier défaut dans l'ordre du document est rendu — les rendre tous
        ferait un message qu'on ne lit pas.
        """
        self.of(event.type)
        fautes = sorted(
            self._validators[event.type].iter_errors(dict(event.properties)),
            key=lambda erreur: list(erreur.absolute_path),
        )
        if fautes:
            premiere = fautes[0]
            ou = premiere.json_path if premiere.absolute_path else "le bloc"
            raise EventError(
                f"bloc de propriétés non conforme pour {event.type!r} : {ou} — {premiere.message}"
            )
