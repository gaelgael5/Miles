"""Résoudre une adresse d'ingestion et lire un corps : deux calculs PURS.

Séparés du service, et pas seulement pour la limite de 300 lignes : ils ne touchent ni la
base ni l'arbre git, donc ils s'éprouvent entièrement sans rien monter. C'est ce qu'on
veut d'un code dont une erreur fait accepter un dépôt sur la mauvaise entrée, ou refuse
un lot que l'appelant a bien formé.
"""

from __future__ import annotations

import json

from miles_socle.parametrage.sources import MAX_BATCH, Entry

from environnement.ingestion.model import (
    BATCH,
    ELEMENT,
    MAX_BODY_BYTES,
    MODES,
    REFUSAL_CORPS_TROP_GRAND,
    REFUSAL_CORPS_VIDE,
    REFUSAL_JSON_INVALIDE,
    REFUSAL_LOT_TROP_GRAND,
    REFUSAL_MODE_AMBIGU,
    REFUSAL_MODE_INCONNU,
    REFUSAL_MODE_NON_DECLARE,
    REFUSAL_MODE_NON_SERVI,
    REFUSAL_OBJET_ATTENDU,
    REFUSAL_SOURCE_ILLISIBLE,
    REFUSAL_SOURCE_INCONNUE,
    REFUSAL_TABLEAU_ATTENDU,
    SERVED_MODES,
    IngestionRefusal,
    Target,
)
from environnement.sources.declarations import DeclaredSources


def exposes(entry: Entry, mode: str) -> bool:
    """Le mode est-il coché par cette entrée ? Public : l'écran d'état le lit aussi.

    Écrit explicitement, et non par réflexion sur un nom : les trois noms du paramétrage
    (`element`, `tableau`, `fichier`) et les trois champs du socle (`element`, `batch`,
    `file`) ne coïncident pas, et une correspondance par chaîne aurait rendu cet écart
    invisible au compilateur — jusqu'au jour où l'un des deux est renommé.
    """
    if mode == ELEMENT:
        return entry.modes.element
    if mode == BATCH:
        return entry.modes.batch
    return entry.modes.file


def target_of(declared: DeclaredSources, source: str, mode: str) -> Target:
    """L'entrée que cette adresse désigne, ou un refus qui dit laquelle corriger.

    **Le mode est l'adresse**, parce que c'est par le choix des méthodes exposées que la
    taille et le rythme d'une intégration se règlent (Gael, 02/11/2026). L'entrée s'en
    déduit : c'est elle qui porte le modèle d'entrée et la chaîne.

    **Deux entrées d'une même source exposant le même mode font REFUSER**, et ne font pas
    choisir la première. L'adresse ne saurait pas de quel modèle l'appelant parle, et
    deviner enverrait le lot dans la mauvaise chaîne — sans que rien ne le signale.
    """
    if mode not in MODES:
        raise IngestionRefusal(REFUSAL_MODE_INCONNU, mode)
    if source in declared.unreadable:
        # Déclarée mais illisible : on ne devine pas ce qu'elle voulait exposer.
        raise IngestionRefusal(REFUSAL_SOURCE_ILLISIBLE, source)
    doc = declared.readable.get(source)
    if doc is None:
        raise IngestionRefusal(REFUSAL_SOURCE_INCONNUE, source)
    candidates = [entry for entry in doc.entries if exposes(entry, mode)]
    if not candidates:
        raise IngestionRefusal(REFUSAL_MODE_NON_DECLARE, mode)
    if len(candidates) > 1:
        raise IngestionRefusal(REFUSAL_MODE_AMBIGU, mode)
    if mode not in SERVED_MODES:
        # Déclaré par le paramétrage, pas encore branché ici. Distinct de « non déclaré » :
        # le geste à faire n'est pas le même — là il faut cocher le mode, ici il faut
        # attendre la story qui le sert.
        raise IngestionRefusal(REFUSAL_MODE_NON_SERVI, mode)
    return Target(source, mode, candidates[0], doc.storage)


def objects_of(mode: str, raw: bytes) -> list[dict[str, object]]:
    """Les objets du lot, lus du corps reçu. Un refus nomme ce qui ne va pas.

    **Un corps vide et un tableau vide ne sont pas la même chose** : le premier est une
    erreur d'appel, le second une ingestion de zéro objet, acceptée. Les confondre
    laisserait un client dont l'export est vide croire qu'il a déposé quelque chose, ou
    l'inverse.
    """
    if len(raw) > MAX_BODY_BYTES:
        raise IngestionRefusal(REFUSAL_CORPS_TROP_GRAND, str(MAX_BODY_BYTES))
    if not raw.strip():
        raise IngestionRefusal(REFUSAL_CORPS_VIDE)
    try:
        lu = json.loads(raw)
    except json.JSONDecodeError as erreur:
        # La position, parce qu'un « JSON invalide » sans elle oblige l'appelant à
        # chercher dans un document qu'il n'a pas sous les yeux.
        raise IngestionRefusal(
            REFUSAL_JSON_INVALIDE, f"ligne {erreur.lineno}, colonne {erreur.colno}"
        ) from None
    if mode == ELEMENT:
        if not isinstance(lu, dict):
            raise IngestionRefusal(REFUSAL_OBJET_ATTENDU)
        return [lu]
    if not isinstance(lu, list):
        raise IngestionRefusal(REFUSAL_TABLEAU_ATTENDU)
    if len(lu) > MAX_BATCH:
        # Le plafond est dit : sans lui, l'appelant ne sait pas s'il doit couper en deux
        # ou en vingt. C'est une décision du paramétrage, pas une limite technique.
        raise IngestionRefusal(REFUSAL_LOT_TROP_GRAND, str(MAX_BATCH))
    for rang, item in enumerate(lu):
        if not isinstance(item, dict):
            raise IngestionRefusal(REFUSAL_OBJET_ATTENDU, f"[{rang}]")
    return list(lu)
