from __future__ import annotations

from typing import Any

from miles_socle.transform.engine import function_registry
from urban_json import FunctionRegistry

from miles.transform.catalog import app_floor, functions_catalog, models_catalog

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
        # Dérivés d'un contrat (47f55d8b) : une énumération n'est pas un objet, et reste listée.
        "contracts/materiel/models/v2/point.yaml": "type: object\nproperties:\n"
        "  x: {type: number}\n",
        "contracts/materiel/models/v2/statut.yaml": "type: string\nenum: [a]\n",
    }

    async def read(path: str) -> str | None:
        return files.get(path)

    models = await models_catalog(sorted(files), read)

    assert [(m.scope, m.name, m.properties) for m in models] == [
        ("retrait", "casse", None),
        ("shared", "personne", ({"name": "nom", "type": "string"},)),
        ("contracts/materiel/v2", "point", ({"name": "x", "type": "number"},)),
        ("contracts/materiel/v2", "statut", ()),
    ]
    assert await app_floor(read) == "2.4.0"
    assert await models_catalog([], read) == []


class TestLeCatalogueDeLIntellisense:
    """Ce que l'éditeur PROPOSE doit être ce que l'évaluation ACCEPTE.

    Jusqu'au 11/11/2026 la route servait le registre global d'`urban-json` — celui qui
    porte en plus tout plugin installé et les fonctions de genre `output`. L'écart valait
    deux noms, et la montée en 0.6.0 l'aurait porté à cinq sans que rien ne le dise : il
    grandissait de lui-même à chaque version. C'est ce test qui l'empêche de revenir.
    """

    def test_le_catalogue_servi_est_celui_du_profil_d_ecriture(self) -> None:
        import urban_json_editor
        from urban_json import default_registry as moteur

        from miles.transform.api_editor import jslt_functions

        servi = {f["name"] for f in jslt_functions().functions}

        assert servi == set(function_registry().names())
        # Discriminant : le registre global en propose davantage, et c'est bien ce qu'on
        # a cessé de servir.
        assert {f["name"] for f in urban_json_editor.catalog(moteur)} - servi == {
            "to_block",
            "to_csv",
            "to_json",
            "to_xml",
            "to_yaml",
        }

    def test_aucune_fonction_de_genre_output_n_est_proposee(self) -> None:
        from miles.transform.api_editor import jslt_functions

        genres = {f.get("kind") for f in jslt_functions().functions}

        # `output` n'a de sens que dans `$directives.output`, que Miles n'admet pas : la
        # proposer enverrait écrire ce que le moteur refuse dans le corps d'un template.
        assert genres == {"function"}

    def test_chaque_fonction_du_coeur_porte_son_lien_de_documentation(self) -> None:
        """L'aide à la signature de l'éditeur 0.4.0 en fait un lien cliquable.

        Le registre de Miles est RECONSTRUIT : sans le report de `doc` et de
        `description_en`, le catalogue serait complet et muet.
        """
        from miles.transform.api_editor import jslt_functions

        servi = {f["name"]: f for f in jslt_functions().functions}

        assert servi["sort"]["doc"] == "fonctions/sort"
        assert servi["sort"]["description_en"]
        # `lazy_args` aussi : c'est lui que l'éditeur lit pour savoir qu'une position
        # reçoit une expression et non une valeur.
        assert servi["sort"]["lazy_args"] == [1]
