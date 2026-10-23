from __future__ import annotations

from pathlib import Path

import yaml

from miles.contracts.derived import derive_models
from miles.contracts.layout import ContractMeta, meta_text
from miles.datamodels.grammar import Problem
from miles.git.workcopy import checkout
from miles.workshop.validation import FileReport, validate_branch
from tests.test_git_versions import BRANCH, TOKEN, _repo

CONTRACT = {
    "openapi": "3.0.3",
    "info": {"title": "Matériel", "version": "1"},
    "paths": {},
    "components": {
        "schemas": {
            "Point": {"type": "object", "properties": {"a": {"$ref": "#/components/schemas/Lieu"}}},
            "Lieu": {"type": "string", "nullable": True},
        }
    },
}
FILE = yaml.safe_dump(CONTRACT)
META = meta_text(ContractMeta("materiel", "Matériel", "sortant"))


def _files(**extra: str) -> dict[str, str]:
    # Dérivés du fichier relu, comme à l'intégration : l'ordre des clés est celui du fichier.
    models = {m.path: m.content for m in derive_models(yaml.safe_load(FILE), "materiel", 1)}
    return (
        {"contracts/materiel/contract.yaml": META, "contracts/materiel/v1.yaml": FILE}
        | models
        | extra
    )


async def _reports(tmp_path: Path, files: dict[str, str]) -> list[FileReport]:
    async with checkout(_repo(tmp_path, files), TOKEN, BRANCH) as copy:
        return await validate_branch(copy)


async def test_a_version_with_its_derived_models_up_to_date_is_valid(tmp_path: Path) -> None:
    assert await _reports(tmp_path, _files()) == []


async def test_missing_edited_or_extra_derived_models_ask_to_be_rederived(tmp_path: Path) -> None:
    stale = [Problem("models", "modeles_derives_desynchronises")]
    missing = {k: v for k, v in _files().items() if not k.endswith("/lieu.yaml")}
    edited = _files(**{"contracts/materiel/models/v1/lieu.yaml": "type: integer\n"})
    extra = _files(**{"contracts/materiel/models/v1/autre.yaml": "type: string\n"})

    for files in (missing, edited, extra):
        reports = await _reports(tmp_path / str(len(files)) / str(id(files)), files)
        assert reports == [FileReport("contracts/materiel/v1.yaml", tuple(stale))]


async def test_derived_models_of_a_missing_version_are_orphans(tmp_path: Path) -> None:
    files = _files(**{"contracts/materiel/models/v4/point.yaml": "type: object\n"})

    assert await _reports(tmp_path, files) == [
        FileReport(
            "contracts/materiel/models/v4/point.yaml", (Problem("", "modele_derive_orphelin"),)
        )
    ]


async def test_an_underivable_version_names_its_schemas(tmp_path: Path) -> None:
    clash = CONTRACT | {"components": {"schemas": {"Point": {}, "point": {}}}}
    files = {
        "contracts/materiel/contract.yaml": META,
        "contracts/materiel/v1.yaml": yaml.safe_dump(clash),
    }

    assert await _reports(tmp_path, files) == [
        FileReport(
            "contracts/materiel/v1.yaml",
            (Problem("components.schemas.point", "noms_de_schema_en_collision", "Point"),),
        )
    ]
