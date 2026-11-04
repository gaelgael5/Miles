"""Ce que chaque méthode d'ingestion attend, pour que l'écran de service puisse l'essayer.

L'écran de santé disait déjà QUELLES adresses existent (story `1c1cd22e`). Ce module dit
ce qu'elles ATTENDENT : le schéma du modèle d'entrée que l'entrée de source déclare, et un
corps d'exemple dérivé de ce schéma. C'est ce qui manque pour qu'une page se lise comme un
contrat et qu'on puisse y déposer sur place (ticket `a78551e5`).

**Le gabarit dépend du MODE, pas seulement du modèle.** `element` dépose un objet,
`tableau` un tableau d'objets : un exemple qui ne colle pas au mode se ferait refuser pour
« tableau attendu », et l'administrateur chercherait l'erreur dans son modèle.

**Un modèle absent ou illisible est NOMMÉ, jamais remplacé par un corps vide.** Un exemple
vide se lirait comme « ce point d'entrée n'attend rien », alors que la vraie information
est qu'une pièce manque à la version servie.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from miles_socle.parametrage.example import example_of
from miles_socle.parametrage.layout import MODEL_RE
from miles_socle.transform.jpath import SplitRefusal, read_stream_split

from environnement.hosting.gitstore import HostedTree
from environnement.ingestion.model import BATCH, FILE, MODES, SERVED_MODES
from environnement.ingestion.resolve import exposes
from environnement.sources.declarations import file_declared_sources
from environnement.storages.declarations import file_model_schema

# Pourquoi la forme attendue n'a pas pu être montrée. Deux motifs distincts : le nom du
# modèle est mal formé dans la déclaration, ou il est bien formé et la version servie ne
# le porte pas. Ils appellent deux gestes différents dans le paramétrage.
REFUSAL_MODEL_INVALID = "modele_invalide"
REFUSAL_MODEL_MISSING = "modele_absent"


@dataclass(frozen=True)
class Endpoint:
    """Un point d'entrée réellement exposé, avec l'adresse que le tiers doit appeler.

    **Ici et non dans l'aperçu de santé**, bien que celui-ci le rende aussi : la boucle
    qui le construit n'existe qu'à un endroit. Deux boucles auraient divergé — un mode
    ajouté d'un seul côté, et l'écran de santé promettrait une adresse que la page de
    contrat ne montre pas.
    """

    source: str
    storage: str
    entry_model: str
    mode: str
    path: str
    # Le gabarit sous lequel le CONTRAT publie cette méthode — l'adresse, elle, est
    # concrète. Les deux sont portées parce qu'elles ne servent pas à la même chose :
    # l'une s'appelle, l'autre désigne l'opération dont un intégrateur lit la signature.
    # Déduire la seconde de la première côté écran aurait été une règle de plus à tenir
    # d'accord avec le routage, et elle aurait rompu au premier chemin littéral ajouté.
    operation: str
    # Faux pour un mode que le paramétrage déclare mais que la stack ne sert pas encore.
    # Distingué, et non masqué : l'afficher comme disponible promettrait un dépôt refusé.
    served: bool
    # Le découpage que l'entrée déclare, tel quel. Porté jusqu'ici parce que le gabarit du
    # mode fichier est un DOCUMENT, et que c'est le découpage qui dit où ses items vont.
    split: str


async def file_endpoints(
    tree: HostedTree, *, operations: Mapping[str, str]
) -> tuple[Endpoint, ...]:
    """Les points d'entrée de la version servie, sans lire aucun modèle.

    Sans lire les modèles, et c'est la raison de séparer ceci de `resolve_methods` :
    l'écran de santé n'a pas besoin des schémas, et les lui faire lire coûterait une
    lecture de fichier par modèle sur une route qu'il interroge souvent.

    `operations` associe chaque mode au gabarit sous lequel sa route est montée, et il est
    passé par la couche qui PORTE les routes : c'est elle qui sait où elles sont. Un mode
    absent de cette table n'a pas de route, donc n'est pas exposé.
    """
    declarees = await file_declared_sources(tree.file_text, await tree.file_paths())
    points: list[Endpoint] = []
    for nom, doc in sorted(declarees.readable.items()):
        for entree in doc.entries:
            points += [
                Endpoint(
                    source=nom,
                    storage=doc.storage,
                    entry_model=entree.source_model,
                    mode=mode,
                    path=operations[mode].format(source=nom, mode=mode),
                    operation=operations[mode],
                    served=mode in SERVED_MODES,
                    split=entree.split,
                )
                for mode in MODES
                if exposes(entree, mode) and mode in operations
            ]
    return tuple(points)


@dataclass(frozen=True)
class Method:
    """Une méthode d'ingestion, telle qu'une page de contrat la présente."""

    source: str
    storage: str
    entry_model: str
    mode: str
    path: str
    # Le gabarit sous lequel le contrat publie cette méthode : c'est par lui que l'écran
    # retrouve sa signature — en-têtes, corps attendu, réponses déclarées.
    operation: str
    # Faux pour un mode que le paramétrage déclare et que la stack ne sert pas encore :
    # il garde sa place et n'offre pas de bouton.
    served: bool
    # Le schéma du modèle d'entrée, renvois résolus. Nul quand on n'a pas pu le lire.
    schema: Any | None
    # Nul quand le schéma a été lu. Sinon il dit ce qui manque.
    model_refusal: str | None
    # Le gabarit à déposer, dans la forme du mode. Nul sans schéma, et nul sur un mode
    # non servi — proposer un corps pour une méthode qui refusera tout serait trompeur.
    example: Any | None


@dataclass(frozen=True)
class IngestionMethods:
    """Lit la version servie et rend ses méthodes. Rien en base, rien en cache.

    Rien en cache parce que l'arbre change quand une version est servie : un schéma
    gardé montrerait la forme d'une version qui n'est plus là, et c'est exactement la
    panne qu'un écran de contrat ne doit pas produire.
    """

    tree: HostedTree

    async def resolve_methods(self, *, operations: Mapping[str, str]) -> tuple[Method, ...]:
        """Les méthodes de toutes les entrées de source, triées par source puis par mode.

        `operations` vient de la couche qui porte les routes : c'est elle qui sait sous
        quel gabarit chaque mode est monté, et donc sous quel nom le contrat le publie.
        """
        points = await file_endpoints(self.tree, operations=operations)
        # Les schémas sont lus UNE fois par modèle, et non une fois par méthode : deux
        # modes d'une même entrée partagent leur modèle d'entrée, et le relire ferait
        # deux lectures de fichier pour un résultat identique.
        lus: dict[str, tuple[Any | None, str | None]] = {}
        methodes: list[Method] = []
        for point in points:
            if point.entry_model not in lus:
                lus[point.entry_model] = await self._schema(point.entry_model)
            schema, refus = lus[point.entry_model]
            methodes.append(
                Method(
                    source=point.source,
                    storage=point.storage,
                    entry_model=point.entry_model,
                    mode=point.mode,
                    path=point.path,
                    operation=point.operation,
                    served=point.served,
                    schema=schema,
                    model_refusal=refus,
                    example=_example(schema, point.mode, point.split),
                )
            )
        return tuple(methodes)

    async def _schema(self, model: str) -> tuple[Any | None, str | None]:
        designation = MODEL_RE.match(model)
        if designation is None:
            return None, REFUSAL_MODEL_INVALID
        schema = await file_model_schema(
            self.tree.file_text, designation["scope"], designation["name"]
        )
        if schema is None:
            return None, REFUSAL_MODEL_MISSING
        return schema, None


def _example(schema: Any | None, mode: str, split: str) -> Any | None:
    if schema is None or mode not in SERVED_MODES:
        return None
    gabarit = example_of(schema)
    # `tableau` dépose un TABLEAU d'objets, `element` un objet. Un seul élément suffit :
    # ce qu'on montre est la forme, et deux éléments identiques n'apprendraient rien.
    if mode == BATCH:
        return [gabarit]
    if mode == FILE:
        return _document(gabarit, split)
    return gabarit


def _document(gabarit: Any, split: str) -> Any | None:
    """Le DOCUMENT attendu en mode fichier : le gabarit, là où le découpage le cherche.

    Un objet seul n'aurait rien appris : ce qu'on dépose est un document, et le découpage
    désigne un tableau DEDANS. Montrer la forme du document est donc la seule façon de
    dire quoi déposer — et elle se dérive du découpage, jamais d'une convention de nom.

    Découpage illisible : aucun gabarit. Le dépôt sera refusé pour cette raison même, et
    proposer un document qui ne colle pas à la déclaration enverrait corriger l'export là
    où c'est le paramétrage qui est en cause.
    """
    lu = read_stream_split(split)
    if isinstance(lu, SplitRefusal):
        return None
    porte: Any = [gabarit]
    for key in reversed(lu.keys):
        porte = [porte] if isinstance(key, int) else {key: porte}
    return porte
