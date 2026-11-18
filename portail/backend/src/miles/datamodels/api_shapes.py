"""Formes échangées par les routes des modèles, et leur calcul depuis un modèle lu.

Les corps que l'écran envoie, ceux qu'il reçoit, et la seule traduction entre le domaine
et eux. Hors des routes parce que ce sont des CONTRATS : on les relit pour savoir ce qui
est promis, sans traverser les gestes qui les produisent.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from miles.datamodels.grammar import MAX_TEXT_BYTES
from miles.datamodels.layout import ModelEntry
from miles.datamodels.usages import Designation, Listing


class ModelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # « shared » pour un modèle transverse, sinon le nom du domaine.
    scope: str
    name: str
    path: str
    # Le `title` du schéma ; absent s'il n'en porte pas.
    label: str | None
    # Tenue par le système : 1 à la création, +1 à chaque enregistrement qui le change.
    version: int | None


class ModelContentOut(ModelOut):
    # Le YAML tel qu'il est dans le dépôt, octet pour octet.
    content: str


class UsageOut(BaseModel):
    """Une déclaration qui DÉSIGNE un modèle (story e36192f8)."""

    model_config = ConfigDict(extra="forbid")
    # « event_type », « storage », « source », « chain_step » ou « model ».
    kind: str
    # L'identifiant du désignateur : c'est par lui que l'écran fait le lien vers lui.
    name: str
    label: str | None
    path: str
    # L'étape d'une chaîne, le rang d'une entrée de source ; absent sinon.
    part: str | None


class BrokenOut(UsageOut):
    # « portée/nom » du modèle désigné, qui n'est pas dans la branche.
    target: str


class ListedOut(ModelOut):
    usages: list[UsageOut]


class ListingOut(BaseModel):
    """La liste des modèles et, à côté, ce qui ne trouve plus sa cible.

    Un objet et non un tableau : les désignations cassées ne se rattachent à AUCUN modèle
    — c'est leur définition — et il n'y avait pas de ligne où les poser. Rendues avec la
    liste plutôt que par une route à elles, elles décrivent le même commit qu'elle.
    """

    model_config = ConfigDict(extra="forbid")
    models: list[ListedOut]
    broken: list[BrokenOut]


class ModelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    # Le nom du fichier et de l'`$id` : un JSON Schema n'a pas de clé de nom.
    name: str
    content: str


class ModelDeclare(BaseModel):
    """Déclaration par label et slug (Gael, 23/10/2026) : le YAML s'écrit à l'édition."""

    model_config = ConfigDict(extra="forbid")
    scope: str
    label: str
    slug: str


class ModelReplace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class SampleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["json", "yaml"]
    # Borné comme les schémas eux-mêmes : un échantillon colle, il ne se téléverse pas
    # sans limite.
    sample: str = Field(max_length=MAX_TEXT_BYTES)


class InferredOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_body: dict[str, Any] = Field(serialization_alias="schema")
    # L'échantillon était une liste : le modèle décrit un de ses éléments. Rendu à
    # l'écran, qui le dit — un dégagement silencieux laisserait croire à une erreur.
    unwrapped: bool


class ExampleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    example: Any


class PathOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    # Nom attendu par le composant <jslt-editor> (urban-json-editor >= 0.2.0) : il
    # affiche « <type> · <description> » sous chaque proposition.
    type: str
    description: str
    # Le `format` du schéma quand il en porte un, vide sinon. À CÔTÉ de `type` et non
    # fondu dedans : <jslt-editor> lit `type` tel quel, et le module d'environnement en
    # dérive le type SQL de ses colonnes projetées. Ajout ADDITIF (10/11/2026) — un
    # consommateur qui ne lit pas ce champ est inchangé.
    format: str


class PathsOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[PathOut]


def model_out(entry: ModelEntry) -> ModelOut:
    return ModelOut(
        scope=entry.scope,
        name=entry.name,
        path=entry.path,
        label=entry.label,
        version=entry.version,
    )


def usage_out(designation: Designation) -> UsageOut:
    return UsageOut(
        kind=designation.kind,
        name=designation.name,
        label=designation.label,
        path=designation.path,
        part=designation.part,
    )


def broken_out(designation: Designation) -> BrokenOut:
    scope, name = designation.target
    return BrokenOut(**usage_out(designation).model_dump(), target=f"{scope}/{name}")


def listing_out(listing: Listing) -> ListingOut:
    return ListingOut(
        models=[
            ListedOut(
                **model_out(listed.entry).model_dump(),
                usages=[usage_out(u) for u in listed.usages],
            )
            for listed in listing.models
        ],
        broken=[broken_out(d) for d in listing.broken],
    )
