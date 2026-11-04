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

from dataclasses import dataclass
from typing import Any

from miles_socle.parametrage.example import example_of
from miles_socle.parametrage.layout import MODEL_RE

from environnement.hosting.gitstore import HostedTree
from environnement.ingestion.model import BATCH, MODES, SERVED_MODES
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
    # Faux pour un mode que le paramétrage déclare mais que la stack ne sert pas encore.
    # Distingué, et non masqué : l'afficher comme disponible promettrait un dépôt refusé.
    served: bool


async def file_endpoints(tree: HostedTree, *, ingest_path: str) -> tuple[Endpoint, ...]:
    """Les points d'entrée de la version servie, sans lire aucun modèle.

    Sans lire les modèles, et c'est la raison de séparer ceci de `resolve_methods` :
    l'écran de santé n'a pas besoin des schémas, et les lui faire lire coûterait une
    lecture de fichier par modèle sur une route qu'il interroge souvent.
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
                    path=ingest_path.format(source=nom, mode=mode),
                    served=mode in SERVED_MODES,
                )
                for mode in MODES
                if exposes(entree, mode)
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

    async def resolve_methods(self, *, ingest_path: str) -> tuple[Method, ...]:
        """Les méthodes de toutes les entrées de source, triées par source puis par mode.

        `ingest_path` est le gabarit de la route, passé par la couche qui la porte : c'est
        elle qui sait où elle est montée.
        """
        points = await file_endpoints(self.tree, ingest_path=ingest_path)
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
                    served=point.served,
                    schema=schema,
                    model_refusal=refus,
                    example=_example(schema, point.mode),
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


def _example(schema: Any | None, mode: str) -> Any | None:
    if schema is None or mode not in SERVED_MODES:
        return None
    gabarit = example_of(schema)
    # `tableau` dépose un TABLEAU d'objets, `element` un objet. Un seul élément suffit :
    # ce qu'on montre est la forme, et deux éléments identiques n'apprendraient rien.
    return [gabarit] if mode == BATCH else gabarit
