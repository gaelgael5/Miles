"""Publier un contrat d'interface : la part commune aux produits qui en publient.

Extrait au socle le 02/11/2026, deuxième usage — le portail publie la surface qu'un agent
emploie, le module d'environnement publie son point d'entrée d'ingestion.

**Ce qui est ici** : réduire la spec engendrée par le cadre à ce qu'on S'ENGAGE à tenir,
et l'écrire de façon reproductible à l'octet près. Ce second point n'est pas cosmétique :
un test compare le fichier publié au contenu attendu, et une sérialisation qui varie
ferait rougir ce test sans qu'aucun contrat n'ait bougé.

**Ce qui reste au produit** : QUELS chemins il publie, et ce que son article promet. Une
spec engendrée décrit le code d'aujourd'hui, accidents compris ; le contrat est ce qu'on
tient. C'est le produit qui sait faire la différence.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def published_spec(
    spec: dict[str, Any], *, info: dict[str, Any], prefixes: tuple[str, ...]
) -> dict[str, Any]:
    """La spec réduite aux chemins publiés, avec seulement les schémas qu'ils atteignent.

    Les schémas sont élagués parce que la spec du cadre porte CEUX DE TOUT LE PRODUIT :
    publiés tels quels, ils décriraient des formes qu'aucune route publiée n'emploie, et
    un lecteur du contrat y verrait des promesses qu'on ne fait pas.
    """
    spec["info"] = info
    spec["paths"] = {
        chemin: valeur for chemin, valeur in spec["paths"].items() if chemin.startswith(prefixes)
    }
    schemas = spec.get("components", {}).get("schemas", {})
    spec["components"] = {
        "schemas": {nom: schemas[nom] for nom in sorted(referenced_schemas(spec, schemas))}
    }
    return spec


def referenced_schemas(spec: dict[str, Any], schemas: dict[str, Any]) -> set[str]:
    """Les schémas atteints depuis les chemins publiés, renvois compris.

    Parcours itératif et non récursif : un schéma qui se référence lui-même — une
    structure en arbre, par exemple — ferait déborder la pile, et c'est une forme
    parfaitement légitime à publier.
    """
    trouves: set[str] = set()
    a_voir: list[Any] = [spec["paths"]]
    while a_voir:
        noeud = a_voir.pop()
        if isinstance(noeud, dict):
            renvoi = noeud.get("$ref")
            if isinstance(renvoi, str) and (nom := renvoi.rsplit("/", 1)[1]) not in trouves:
                trouves.add(nom)
                a_voir.append(schemas.get(nom, {}))
            a_voir.extend(valeur for clef, valeur in noeud.items() if clef != "$ref")
        elif isinstance(noeud, list):
            a_voir.extend(noeud)
    return trouves


def dump(value: Any) -> str:
    """Le contenu d'un fichier publié, à l'octet près.

    `ensure_ascii=False` parce qu'un contrat se relit, et qu'une description française
    échappée en `\\uXXXX` ne se relit pas. Le retour à la ligne final parce que tout le
    dépôt en porte un, et que son absence ferait un diff sur la dernière ligne.
    """
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def file_write_contracts(directory: Path, rendered: dict[str, str]) -> None:
    for nom, contenu in rendered.items():
        (directory / nom).write_text(contenu, encoding="utf-8")
