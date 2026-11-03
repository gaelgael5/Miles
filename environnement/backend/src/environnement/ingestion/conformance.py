"""L'objet transformé respecte-t-il le modèle du storage ? Sinon il est rejeté.

**Avant d'atteindre la table** (critère 11 de la story `d680e811`) : la table ne décrit
pas le modèle — elle porte un `jsonb` et des colonnes dérivées —, donc elle accepterait
sans broncher un objet amputé d'une propriété obligatoire. Le défaut se découvrirait des
mois plus tard, sur un écran qui lit une propriété absente.

Le validateur est celui du module de paramétrage, à la version près : les deux lisent les
mêmes fichiers, et deux versions accepteraient deux choses différentes du même schéma.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


class ModelViolation(Exception):
    """L'objet transformé ne respecte pas le modèle. `detail` nomme le premier écart.

    Le PREMIER et non tous : le compte-rendu nomme un objet par ligne, et une liste de
    quinze écarts sur un objet noierait les autres objets du lot. Le premier écart, avec
    son chemin, suffit à corriger le template — qui est l'endroit où l'on corrige.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def check_conformance(objet: Any, schema: Any) -> None:
    """Lève `ModelViolation` au premier écart ; ne rend rien quand l'objet est conforme.

    Les écarts sont TRIÉS avant d'en prendre un : `iter_errors` ne promet aucun ordre, et
    un message qui change d'un appel à l'autre pour le même objet rendrait un
    compte-rendu non reproductible — exactement ce que la persistance du lot brut
    cherche à garantir.
    """
    erreurs = sorted(
        Draft202012Validator(schema).iter_errors(objet),
        key=lambda e: (list(e.absolute_path), e.validator or "", e.message),
    )
    if not erreurs:
        return
    premier = erreurs[0]
    chemin = "$" + "".join(f"[{p!r}]" for p in premier.absolute_path)
    raise ModelViolation(f"{chemin}: {premier.message}")
