"""Catalogue des fonctions JSLT, pour l'intellisense de l'éditeur (Gael, 24/10/2026).

Le composant `<jslt-editor>` va chercher ce catalogue à l'URL qu'on lui donne. Il vient
du registre GLOBAL d'`urban-json` (`default_registry`), et non du registre d'écriture de
Miles : ce dernier n'admet que les fonctions du cœur du moteur et refuse les plugins
installés (`miles_socle.transform.engine._registry`, garde du 22/10/2026).

Les deux listes ne coïncident donc pas tout à fait, et l'écart est mesuré, non supposé :
au 11/11/2026 il vaut exactement `to_json` et `to_block`, deux fonctions `kind="output"`
que le moteur refuse de toute façon dans le corps d'un template — elles n'ont de sens que
dans `$directives.output`. L'écart est bénin tant qu'aucun plugin n'est installé dans
l'image du portail ; le jour où il y en aura un, cette route proposera à la saisie ce que
le profil d'écriture rejettera, et c'est ici qu'il faudra passer le registre de Miles.
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
