from __future__ import annotations

from typing import Any

from urban_json import FunctionRegistry

from miles.transform.catalog import app_floor, functions_catalog, models_catalog
from miles.transform.engine import function_registry

PERSONNE = (
    "$schema: https://json-schema.org/draft/2020-12/schema\n$id: miles:/shared/personne\n"
    "title: Personne\ntype: object\nproperties:\n  nom:\n    type: string\n"
)


def _documented(ctx: Any, value: str = "") -> str:
    """Met en majuscules.

    Une valeur absente reste absente.
    """
    return value.upper()


def _bare(ctx, value):  # type: ignore[no-untyped-def]
    return value


def test_catalogue_follows_the_registry_without_any_list_kept_by_hand() -> None:
    registry = FunctionRegistry()
    registry.register("majuscules", _documented, (), "Met en majuscules.")

    added = [e.name for e in functions_catalog(registry)]
    registry = FunctionRegistry()
    removed = [e.name for e in functions_catalog(registry)]

    assert (added, removed) == (["majuscules"], [])


def test_entry_carries_its_semantics_and_an_undocumented_one_is_flagged() -> None:
    registry = FunctionRegistry()
    registry.register("majuscules", _documented, (), "Met en majuscules.")
    registry.register("nue", _bare, (), "")

    documented, bare = sorted(functions_catalog(registry), key=lambda e: e.name)

    assert documented.signature == "majuscules(value)"
    assert "Une valeur absente reste absente." in documented.documentation
    assert documented.missing == ()
    assert bare.missing == ("description", "types")


def test_miles_catalogue_lists_the_strict_cast_and_core_functions() -> None:
    names = {e.name: e for e in functions_catalog(function_registry())}

    assert {"convert", "concat", "upper", "sum"} <= names.keys()
    assert "jamais une valeur par défaut" in names["convert"].description


async def test_models_come_from_the_branch_with_their_properties() -> None:
    files = {
        "shared/messages/personne.yaml": PERSONNE,
        "domains/retrait/messages/casse.yaml": "type: texte\n",
        "manifest.json": '{"format_version": 1, "min_app_version": "2.4.0", "capabilities": []}',
    }

    async def read(path: str) -> str | None:
        return files.get(path)

    models = await models_catalog(sorted(files), read)

    assert [(m.scope, m.name, m.properties) for m in models] == [
        ("retrait", "casse", None),
        ("shared", "personne", ({"name": "nom", "type": "string"},)),
    ]
    assert await app_floor(read) == "2.4.0"
    assert await models_catalog([], read) == []
