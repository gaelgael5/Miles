"""Catalogue des fonctions JSLT, pour l'intellisense de l'éditeur (Gael, 24/10/2026).

Le composant `<jslt-editor>` va chercher ce catalogue à l'URL qu'on lui donne, et ce
catalogue est **celui du registre d'écriture de Miles** : l'éditeur ne propose donc que ce
que l'évaluation acceptera.

**Il ne l'était pas jusqu'au 11/11/2026**, et c'était un défaut, non un choix : la route
servait le registre GLOBAL d'`urban-json`, qui porte en plus tout plugin installé (HTTP,
SQL…) et les fonctions de genre `output`. L'écart était bénin tant qu'aucun plugin n'était
dans l'image — il valait `to_json` et `to_block`, refusées de toute façon dans le corps
d'un template —, mais il grandissait tout seul : la montée en 0.6.0 l'aurait porté à cinq
noms (`to_csv`, `to_xml`, `to_yaml` s'y ajoutent). `urban_json_editor.catalog()` accepte
un registre depuis 0.3.0 ; il suffisait de le lui donner.

Ce que le registre de Miles doit donc porter, et qu'il porte depuis le même jour : le
`doc` et le `description_en` de chaque fonction. L'aide à la signature de l'éditeur 0.4.0
en fait un lien vers la page de référence, dans la langue du lecteur ; un registre
reconstruit sans ces champs aurait rendu un catalogue sans lien ni description anglaise,
et l'éditeur n'aurait pas eu de quoi le dire.
"""

from __future__ import annotations

from typing import Any

import urban_json_editor
from fastapi import APIRouter
from miles_socle.transform.engine import function_registry
from pydantic import BaseModel, ConfigDict

# Assets du composant. Sous /api : seul préfixe relayé par le nginx du front.
JSLT_EDITOR_PATH = "/api/jslt-editor"

router = APIRouter()


class CatalogOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    functions: list[dict[str, Any]]


@router.get("/api/jslt-functions", response_model=CatalogOut)
def jslt_functions() -> CatalogOut:
    # Le registre de Miles, pas le registre global : voir l'en-tête du module.
    return CatalogOut(functions=urban_json_editor.catalog(function_registry()))
