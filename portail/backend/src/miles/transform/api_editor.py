"""Catalogue des fonctions JSLT, pour l'intellisense de l'éditeur (Gael, 24/10/2026).

Le composant `<jslt-editor>` va chercher ce catalogue à l'URL qu'on lui donne. Il vient
du registre d'`urban-json` lui-même : les fonctions proposées à la saisie sont donc
exactement celles que la transformation saura exécuter, plugins compris.
"""

from __future__ import annotations

from typing import Any

import urban_json_editor
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

# Assets du composant. Sous /api : seul préfixe relayé par le nginx du front.
JSLT_EDITOR_PATH = "/api/jslt-editor"

router = APIRouter()


class CatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    functions: list[dict[str, Any]]


@router.get("/api/jslt-functions", response_model=CatalogOut)
def jslt_functions() -> CatalogOut:
    return CatalogOut(functions=urban_json_editor.catalog())
