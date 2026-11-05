"""Le contrat publié, restreint à UNE source et rendu CONCRET.

Le contrat versionné décrit des gabarits — `/ingest/{source}/{mode}` —, parce qu'il vaut
pour tout environnement quel que soit son paramétrage. Un intégrateur, lui, reçoit une
adresse : `/ingest/integration-des-sites/tableau`. Ce module substitue les adresses
réelles de la source et retire les paramètres de chemin qui n'en sont plus — ils sont
écrits dans l'adresse.

**Côté serveur depuis le 05/11/2026** (Gael) : le document se pointe par une URL qu'un
intégrateur ouvre sans compte, et il doit alors être le MÊME que celui que l'écran
montre. Spécialisé dans le navigateur, il n'existait que là — on ne pouvait ni le
télécharger ni le donner à un générateur de client, et une seconde implémentation côté
serveur aurait divergé de ce que la page affiche.

Rien n'est inventé : tout vient du contrat publié et des méthodes que la version servie
déclare. Recopier une description ou un en-tête ici en aurait fait une seconde vérité.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from environnement.ingestion.methods import Method


def _dict(valeur: Any) -> dict[str, Any]:
    return dict(valeur) if isinstance(valeur, dict) else {}


def _body(request_body: dict[str, Any], method: Method) -> dict[str, Any]:
    """Le corps attendu, dit avec le MODÈLE de l'entrée de source quand le mode le détermine.

    Le contrat générique ne peut annoncer qu'un objet ou un tableau d'objets : il ne
    connaît pas le modèle, qui vient du paramétrage. Ici on le connaît, et c'est ce que
    l'intégrateur est venu chercher.

    **Le mode `fichier` garde le schéma du contrat** : son corps est un DOCUMENT dont le
    découpage déclaré par la source désigne un tableau quelque part dedans — le modèle
    décrit les items, pas le document. L'annoncer comme corps serait faux, et un contrat
    faux coûte plus cher qu'un contrat vague.
    """
    schema: Any | None = None
    if method.mode == "element":
        schema = method.schema
    elif method.mode == "tableau":
        schema = {"type": "array", "items": method.schema}
    contenus = {}
    for media_type, media in _dict(request_body.get("content")).items():
        if media_type != "application/json":
            contenus[media_type] = media
            continue
        decrit = _dict(media)
        if schema is not None:
            decrit["schema"] = schema
        if method.example is not None:
            # Le gabarit que l'essai sème dans sa zone de saisie : les deux viennent du
            # même endroit, et les voir identiques des deux côtés fait partie du contrat.
            decrit["example"] = method.example
        contenus[media_type] = decrit
    return {**request_body, "content": contenus}


def source_spec(
    spec: dict[str, Any], methods: Sequence[Method], source: str
) -> dict[str, Any] | None:
    """Le contrat de cette source, ou None si la version servie ne la déclare pas.

    None et non un contrat vide : une source inconnue est une adresse fautive, et rendre
    un document sans chemin la ferait passer pour une source qui n'expose rien.
    """
    siennes = [method for method in methods if method.source == source]
    if not siennes:
        return None
    gabarits = _dict(spec.get("paths"))
    chemins: dict[str, Any] = {}
    for method in siennes:
        post = _dict(_dict(gabarits.get(method.operation)).get("post"))
        parametres = post.get("parameters")
        operation = {
            **post,
            # Les paramètres de CHEMIN disparaissent : l'adresse n'a plus de gabarit, et
            # un client engendré demanderait une valeur pour un segment déjà écrit.
            "parameters": [
                p
                for p in (parametres if isinstance(parametres, list) else [])
                if _dict(p).get("in") != "path"
            ],
        }
        if method.schema is not None or method.example is not None:
            operation["requestBody"] = _body(_dict(post.get("requestBody")), method)
        chemins[method.path] = {"post": operation}
    return {**spec, "paths": chemins}
