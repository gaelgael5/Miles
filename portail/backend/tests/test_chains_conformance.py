"""Le template confronté au modèle qu'il annonce, sans jamais l'exécuter.

Chaque test donne un modèle et un template, et dit CE QUI EST SÛR : un écart ne se
signale que lorsque le texte du template suffit à l'établir.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from miles.chains.conformance import Divergence, ast_of, divergences
from miles.datamodels.layout import model_path


def _read(models: dict[str, Any]) -> Any:
    """Lecture de la branche doublée : (portée, nom) → schéma, déjà en YAML."""
    texts = {model_path(*key.split("/")): yaml.safe_dump(schema) for key, schema in models.items()}

    async def read(path: str) -> str | None:
        return texts.get(path)

    return read


async def _found(
    models: dict[str, Any], template: str, model: str | None = "miles:/shared/colis"
) -> list[tuple[str, str]]:
    ast = ast_of(template)
    # La garde qui évite le faux vert : un template qui ne PARSE pas ne produit aucune
    # alerte, et le test passerait pour la mauvaise raison. Mesuré le 01/11/2026 — la
    # première version d'un de ces tests écrivait `@.Code` là où le moteur veut `$.Code`.
    assert ast is not None, "template d'essai illisible : le test ne mesurerait rien"
    return [(d.path, d.code) for d in await divergences(_read(models), model, ast)]


COLIS = {
    "shared/colis": {
        "type": "object",
        "required": ["ref"],
        "properties": {"ref": {"type": "string"}, "poids": {"type": "number"}},
    }
}


@pytest.mark.asyncio
async def test_a_template_that_writes_exactly_the_model_says_nothing() -> None:
    assert await _found(COLIS, '{ "ref": $.Reference, "poids": $.Poids }') == []


@pytest.mark.asyncio
async def test_a_property_the_model_does_not_declare_is_named() -> None:
    # Le cas qui vaut la fonctionnalité : une faute de frappe sur un nom de propriété.
    assert await _found(COLIS, '{ "ref": $.Reference, "poid": $.Poids }') == [
        ("$.poid", "propriete_hors_modele")
    ]


@pytest.mark.asyncio
async def test_a_required_property_the_template_omits_is_named() -> None:
    assert await _found(COLIS, '{ "poids": $.Poids }') == [
        ("$.ref", "propriete_obligatoire_absente")
    ]


@pytest.mark.asyncio
async def test_an_optional_property_the_template_omits_is_not_a_reproach() -> None:
    assert await _found(COLIS, '{ "ref": $.Reference }') == []


@pytest.mark.asyncio
async def test_both_kinds_of_gap_are_rendered_together() -> None:
    """Tous les écarts, pas seulement le premier : on corrige en une passe."""
    assert await _found(COLIS, '{ "poid": $.Poids }') == [
        ("$.poid", "propriete_hors_modele"),
        ("$.ref", "propriete_obligatoire_absente"),
    ]


@pytest.mark.asyncio
async def test_an_object_written_where_the_model_announces_a_string() -> None:
    models = {
        "shared/colis": {"type": "object", "properties": {"ref": {"type": "string"}}},
    }
    assert await _found(models, '{ "ref": { "interne": $.Reference } }') == [
        ("$.ref", "objet_inattendu")
    ]


@pytest.mark.asyncio
async def test_an_array_written_where_the_model_announces_an_object() -> None:
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {"client": {"type": "object", "properties": {"nom": {"type": "string"}}}},
        },
    }
    assert await _found(models, '{ "client": [ { "nom": $.Nom } ] }') == [
        ("$.client", "tableau_inattendu")
    ]


@pytest.mark.asyncio
async def test_the_descent_goes_through_a_nested_object() -> None:
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {
                "client": {
                    "type": "object",
                    "required": ["nom"],
                    "properties": {"nom": {"type": "string"}},
                }
            },
        },
    }
    assert await _found(models, '{ "client": { "prenom": $.Prenom } }') == [
        ("$.client.prenom", "propriete_hors_modele"),
        ("$.client.nom", "propriete_obligatoire_absente"),
    ]


@pytest.mark.asyncio
async def test_every_element_of_an_array_is_confronted_to_its_items() -> None:
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {
                "lignes": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"code": {"type": "string"}}},
                }
            },
        },
    }
    template = '{ "lignes": [ { "code": $.A }, { "cdoe": $.B } ] }'

    assert await _found(models, template) == [("$.lignes[1].cdoe", "propriete_hors_modele")]


@pytest.mark.asyncio
async def test_a_loop_over_a_source_keeps_the_shape_of_its_element() -> None:
    """Un élément porteur d'un `$source` est une boucle : sa forme se vérifie une fois."""
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {
                "lignes": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"code": {"type": "string"}}},
                }
            },
        },
    }
    template = '{ "lignes": [ { "$source": $.Items, "cdoe": $.Code } ] }'

    assert await _found(models, template) == [("$.lignes[0].cdoe", "propriete_hors_modele")]


@pytest.mark.asyncio
async def test_a_source_at_the_root_stays_an_object() -> None:
    """`$source` à la racine ne fait pas un tableau : il déplace la source des chemins."""
    assert await _found(COLIS, '{ "$source": $.Colis, "ref": $.Reference }') == []


@pytest.mark.asyncio
async def test_a_value_the_template_computes_is_never_a_reproach() -> None:
    """Chemin et fonction : leur résultat dépend des données, on se tait.

    Une CONSTANTE, elle, se lit : elle est jugée par les tests de type ci-dessous.
    """
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {"client": {"type": "object", "properties": {"nom": {"type": "string"}}}},
        },
    }
    for value in ("$.Client", "concat($.A, $.B)"):
        assert await _found(models, f'{{ "client": {value} }}') == []


# --- Le type écrit, confronté au type annoncé (Gael, 01/11/2026) ---


def _typed(kind: object) -> dict[str, Any]:
    return {"shared/colis": {"type": "object", "properties": {"v": {"type": kind}}}}


@pytest.mark.asyncio
async def test_a_constant_of_the_wrong_type_is_named() -> None:
    assert await _found(_typed("number"), '{ "v": "douze" }') == [("$.v", "texte_inattendu")]
    assert await _found(_typed("string"), '{ "v": 12 }') == [("$.v", "nombre_inattendu")]
    assert await _found(_typed("string"), '{ "v": true }') == [("$.v", "booleen_inattendu")]


@pytest.mark.asyncio
async def test_a_constant_of_the_announced_type_says_nothing() -> None:
    assert await _found(_typed("string"), '{ "v": "douze" }') == []
    assert await _found(_typed("boolean"), '{ "v": false }') == []


@pytest.mark.asyncio
async def test_an_integer_satisfies_a_number_but_a_decimal_does_not_satisfy_an_integer() -> None:
    """Le modèle qui annonce `number` accepte les deux ; l'inverse n'est pas vrai."""
    assert await _found(_typed("number"), '{ "v": 12 }') == []
    assert await _found(_typed("integer"), '{ "v": 1.5 }') == [("$.v", "nombre_inattendu")]
    assert await _found(_typed("integer"), '{ "v": 12 }') == []


@pytest.mark.asyncio
async def test_null_is_an_error_only_where_the_model_refuses_it() -> None:
    assert await _found(_typed("string"), '{ "v": null }') == [("$.v", "nul_inattendu")]
    assert await _found(_typed(["string", "null"]), '{ "v": null }') == []


@pytest.mark.asyncio
async def test_a_cast_says_the_type_it_produces() -> None:
    """`#decimal` rend un nombre quoi qu'il arrive : le type est sûr sans exécuter."""
    assert await _found(_typed("string"), '{ "v": $.x#decimal }') == [("$.v", "nombre_inattendu")]
    assert await _found(_typed("number"), '{ "v": $.x#decimal }') == []
    assert await _found(_typed("string"), '{ "v": $.x#string }') == []


@pytest.mark.asyncio
async def test_a_type_the_model_leaves_open_is_never_a_reproach() -> None:
    models = {"shared/colis": {"type": "object", "properties": {"v": {"title": "Libre"}}}}

    assert await _found(models, '{ "v": "douze" }') == []


@pytest.mark.asyncio
async def test_the_alert_names_the_type_the_model_announced() -> None:
    found = await divergences(
        _read(_typed(["string", "null"])), "miles:/shared/colis", ast_of('{ "v": 12 }')
    )

    assert found == (Divergence("$.v", "nombre_inattendu", "string|null"),)


@pytest.mark.asyncio
async def test_an_internal_reference_is_followed() -> None:
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {"client": {"$ref": "#/$defs/personne"}},
            "$defs": {"personne": {"type": "object", "properties": {"nom": {"type": "string"}}}},
        },
    }
    assert await _found(models, '{ "client": { "prenom": $.P } }') == [
        ("$.client.prenom", "propriete_hors_modele")
    ]


@pytest.mark.asyncio
async def test_a_reference_to_another_model_is_followed() -> None:
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {"client": {"$ref": "miles:/shared/personne"}},
        },
        "shared/personne": {"type": "object", "properties": {"nom": {"type": "string"}}},
    }
    assert await _found(models, '{ "client": { "prenom": $.P } }') == [
        ("$.client.prenom", "propriete_hors_modele")
    ]


@pytest.mark.asyncio
async def test_a_model_that_references_itself_stops_instead_of_overflowing() -> None:
    models = {
        "shared/colis": {
            "type": "object",
            "properties": {"parent": {"$ref": "miles:/shared/colis"}},
        }
    }
    deep = '{ "parent": ' * 20 + "$.X" + " }" * 20

    # Rendu, jamais un débordement de pile : la descente est bornée.
    assert await _found(models, deep) == []


@pytest.mark.asyncio
async def test_an_unquotable_property_name_is_rendered_bracketed() -> None:
    models = {"shared/colis": {"type": "object", "properties": {"a.b": {"type": "string"}}}}

    assert await _found(models, '{ "a.c": $.X }') == [('$["a.c"]', "propriete_hors_modele")]


@pytest.mark.asyncio
async def test_a_step_without_a_destination_model_says_nothing() -> None:
    assert await _found(COLIS, '{ "poid": $.X }', model=None) == []


@pytest.mark.asyncio
async def test_a_model_that_cannot_be_found_says_nothing() -> None:
    """Une absence n'est pas une contradiction (règle posée par Gael le 25/10/2026)."""
    assert await _found({}, '{ "poid": $.X }') == []


@pytest.mark.asyncio
async def test_a_model_that_declares_no_properties_says_nothing() -> None:
    assert await _found({"shared/colis": {"type": "object"}}, '{ "poid": $.X }') == []


@pytest.mark.asyncio
async def test_a_template_that_cannot_be_read_says_nothing() -> None:
    """Il est déjà refusé à l'écriture : en reparler ferait deux messages pour un défaut."""
    assert ast_of("{ ceci n'est pas") is None
    assert await divergences(_read(COLIS), "miles:/shared/colis", None) == ()


@pytest.mark.asyncio
async def test_a_reference_that_designates_nothing_says_nothing() -> None:
    assert await _found(COLIS, '{ "poid": $.X }', model="pas-une-uri") == []


@pytest.mark.asyncio
async def test_the_divergence_carries_the_kind_the_model_announced() -> None:
    models = {"shared/colis": {"type": "object", "properties": {"ref": {"type": "string"}}}}

    found = await divergences(
        _read(models), "miles:/shared/colis", ast_of('{ "ref": { "a": $.X } }')
    )

    assert found == (Divergence("$.ref", "objet_inattendu", "string"),)
