"""L'objet transformé respecte-t-il le modèle du storage ? Sinon il est rejeté.

**Avant d'atteindre la table** (critère 11 de la story `d680e811`) : la table ne décrit
pas le modèle — elle porte un `jsonb` et des colonnes dérivées —, donc elle accepterait
sans broncher un objet amputé d'une propriété obligatoire. Le défaut se découvrirait des
mois plus tard, sur un écran qui lit une propriété absente.

Le validateur est celui du module de paramétrage, à la version près : les deux lisent les
mêmes fichiers, et deux versions accepteraient deux choses différentes du même schéma.

## Le chemin rapide, et pourquoi il est borné comme il l'est

`jsonschema` coûte 52,9 µs par objet, un validateur COMPILÉ 2,5 µs : mesuré le
07/11/2026, **vingt fois** sur le poste qui était alors le second d'un import. Mais le contrôle
du modèle est une GARDE, et « le modèle en base doit être valide » est une contrainte non
négociable (Gael, 07/11/2026). Deux dispositions rendent le chemin rapide sûr :

1. **Il ne décide que d'ACCEPTER.** S'il refuse, le verdict et le message sont redemandés
   à l'autorité. Les refus sont rares, le coût est donc nul, le compte-rendu garde son
   message au caractère près, et un refus à tort du validateur compilé est impossible —
   ce qui écarte d'emblée `format` et `contentSchema`, mesurés plus stricts que l'autorité.
2. **Il ne s'applique qu'aux schémas dont TOUS les mots-clés sont dans `AGREED`**, liste
   établie par la mesure et tenue par `tests/test_ingestion_modele_rapide.py`, qui compare
   les deux validateurs mot-clé par mot-clé. Tout mot-clé inconnu, tout `$schema` d'un
   autre dialecte, toute forme que l'énumération ne sait pas parcourir renvoient à
   l'autorité : le défaut est de se méfier.

**Mesure décisive du 07/11/2026, qui a écarté la forme « on compile, et on se replie si la
compilation échoue » :** sur 46 formes éprouvées, UNE SEULE refuse de compiler (`$anchor`).
Dix compilent et rendent un autre verdict, dont huit en ACCEPTANT ce que l'autorité refuse
— `prefixItems`, `maxContains`, `minContains`, `unevaluatedItems`, `dependentRequired`,
`dependentSchemas`, `unevaluatedProperties`, `$dynamicRef`. Un modèle portant
`dependentRequired` aurait donc compilé sans un bruit et laissé entrer des objets
incomplets. Se replier sur l'échec de compilation n'aurait attrapé qu'un cas sur onze.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import fastjsonschema
from jsonschema import Draft202012Validator
from miles_socle.schemas import (
    MAX_SCHEMA_DEPTH,
    SCHEMA_LIST,
    SCHEMA_TABLE,
    SCHEMA_VALUE,
)

# Le dialecte des modèles du dépôt. Le chemin rapide l'IMPOSE au validateur compilé, parce
# que c'est ce que fait l'autorité : `Draft202012Validator` évalue en 2020-12 quel que soit
# le `$schema` écrit dans le document. Sans cette imposition, le compilé suivrait la
# déclaration et `items` changerait de sens entre les deux — en 2019-09 un tableau d'`items`
# valide un tuple, en 2020-12 c'est `prefixItems` qui le fait.
DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Les mots-clés sur lesquels les deux validateurs rendent le MÊME verdict. Cette liste
# n'est pas tenue à la main : chacun de ses membres a son cas dans
# `tests/test_ingestion_modele_rapide.py`, et le test rougit si une montée de version du
# validateur compilé fait diverger l'un d'eux. Un mot-clé absent d'ici n'est pas « non
# supporté » — il est seulement non MESURÉ, et renvoie à l'autorité.
AGREED = frozenset(
    {
        # Annotations : sans effet sur le verdict.
        "$comment",
        "$id",
        "$schema",
        "default",
        "deprecated",
        "description",
        "examples",
        "readOnly",
        "title",
        "writeOnly",
        # Généralités.
        "const",
        "enum",
        "type",
        # Nombres.
        "exclusiveMaximum",
        "exclusiveMinimum",
        "maximum",
        "minimum",
        "multipleOf",
        # Chaînes.
        "maxLength",
        "minLength",
        "pattern",
        # Tableaux. `contains` SEUL : `maxContains` et `minContains` divergent.
        "contains",
        "items",
        "maxItems",
        "minItems",
        "uniqueItems",
        # Objets.
        "additionalProperties",
        "maxProperties",
        "minProperties",
        "patternProperties",
        "properties",
        "propertyNames",
        "required",
        # Combinaisons.
        "allOf",
        "anyOf",
        "else",
        "if",
        "not",
        "oneOf",
        "then",
        # Références internes. `$anchor` et `$dynamicRef` en sont exclus.
        "$defs",
        "$ref",
    }
)


class ModelViolation(Exception):
    """L'objet transformé ne respecte pas le modèle. `detail` nomme le premier écart.

    Le PREMIER et non tous : le compte-rendu nomme un objet par ligne, et une liste de
    quinze écarts sur un objet noierait les autres objets du lot. Le premier écart, avec
    son chemin, suffit à corriger le template — qui est l'endroit où l'on corrige.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class ModelValidator:
    """L'AUTORITÉ, et le chemin rapide quand il a été mesuré sûr pour ce schéma.

    Les deux ensemble et non l'un ou l'autre : c'est ce qui permet au rapide de ne
    décider que d'accepter, et à l'autorité de rendre tous les refus.
    """

    authority: Draft202012Validator
    fast: Callable[[Any], Any] | None

    @property
    def schema(self) -> Any:
        """Le schéma, lisible comme avant : une seule source, pas deux champs à tenir."""
        return self.authority.schema


def model_validator(schema: Any) -> ModelValidator:
    """Le validateur du modèle, construit UNE FOIS par dépôt.

    8,4 µs par construction de l'autorité, mesurés le 06/11/2026, et 3 ms pour compiler le
    chemin rapide — à payer une fois, jamais par objet. C'est ici que l'on décide si le
    schéma est éligible au chemin rapide, et nulle part ailleurs : la décision ne dépend
    que du schéma, donc elle ne doit pas être reprise à chaque item.
    """
    return ModelValidator(Draft202012Validator(schema), _compiled(schema))


def check_conformance(objet: Any, validator: ModelValidator) -> None:
    """Lève `ModelViolation` au premier écart ; ne rend rien quand l'objet est conforme."""
    if validator.fast is not None:
        try:
            validator.fast(objet)
        except fastjsonschema.JsonSchemaException:
            # Refus du chemin rapide : il ne tranche PAS. L'autorité reprend la main, et
            # c'est elle qui refuse ou accepte — un refus à tort du compilé est donc sans
            # effet, et le message du compte-rendu reste exactement le sien.
            pass
        else:
            return
    _refuse_by_authority(objet, validator.authority)


def _refuse_by_authority(objet: Any, authority: Draft202012Validator) -> None:
    """Le verdict de l'autorité, et son message.

    Les écarts sont TRIÉS avant d'en prendre un : `iter_errors` ne promet aucun ordre, et
    un message qui change d'un appel à l'autre pour le même objet rendrait un
    compte-rendu non reproductible — exactement ce que la persistance du lot brut
    cherche à garantir.
    """
    erreurs = sorted(
        authority.iter_errors(objet),
        key=lambda e: (list(e.absolute_path), e.validator or "", e.message),
    )
    if not erreurs:
        return
    premier = erreurs[0]
    chemin = "$" + "".join(f"[{p!r}]" for p in premier.absolute_path)
    raise ModelViolation(f"{chemin}: {premier.message}")


def _compiled(schema: Any) -> Callable[[Any], Any] | None:
    """Le validateur compilé si ce schéma est éligible, sinon None.

    Aucun refus n'est levé ici : un schéma non éligible n'est pas fautif, il est seulement
    validé par l'autorité. Il n'y a donc rien à dire au déposant.
    """
    mots = _keywords(schema)
    if mots is None or not mots <= AGREED:
        return None
    declare = schema if isinstance(schema, bool) else {**schema, "$schema": DIALECT}
    try:
        compiled: Callable[[Any], Any] = fastjsonschema.compile(declare)
    except fastjsonschema.JsonSchemaDefinitionException:
        # Le compilé refuse ce schéma. Sans conséquence : l'autorité le valide. Mesuré
        # rare — un cas sur quarante-six —, ce qui est précisément la raison pour laquelle
        # ce repli ne peut pas être la SEULE garde (voir la docstring du module).
        return None
    return compiled


def _keywords(schema: Any) -> frozenset[str] | None:
    """Tous les mots-clés du schéma, à tous les niveaux, ou None si l'on ne sait pas.

    **None n'est pas une erreur, c'est un aveu** : la forme rencontrée n'est pas celle
    qu'on sait parcourir, donc on ne se prononce pas et l'autorité tranche. Arrive sur un
    `items` écrit comme un tableau (forme d'un dialecte antérieur), sur un `$schema` d'un
    autre dialecte, et sur une imbrication au-delà de la borne du socle.

    Le parcours suit les tables du socle, et c'est indispensable : dans
    `{"properties": {"items": {...}}}`, `items` est un NOM de propriété. Un parcours
    aveugle le prendrait pour un mot-clé et renverrait tout modèle portant une propriété
    ainsi nommée vers l'autorité — ou, pire côté portail, réécrirait cette propriété.
    """
    trouves: set[str] = set()
    pile: list[tuple[Any, int]] = [(schema, 0)]
    while pile:
        noeud, profondeur = pile.pop()
        if isinstance(noeud, bool):
            # Un schéma booléen est légal et n'a pas de mot-clé : `true` accepte tout,
            # `false` refuse tout, et les deux sont mesurés en accord.
            continue
        if not isinstance(noeud, dict) or profondeur > MAX_SCHEMA_DEPTH:
            return None
        for cle, valeur in noeud.items():
            if cle == "$schema" and valeur != DIALECT:
                return None
            trouves.add(cle)
            if cle in SCHEMA_VALUE:
                pile.append((valeur, profondeur + 1))
            elif cle in SCHEMA_LIST and isinstance(valeur, list):
                pile.extend((element, profondeur + 1) for element in valeur)
            elif cle in SCHEMA_TABLE and isinstance(valeur, dict):
                pile.extend((sous, profondeur + 1) for sous in valeur.values())
    return frozenset(trouves)
