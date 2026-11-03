"""L'empreinte d'un objet transformé : ce qui décide de réécrire son corps, ou non.

**Elle porte sur le MODÈLE TRANSFORMÉ, jamais sur le message source** (décision de la
story `d680e811`, et interdit explicite). La raison : elle devient insensible à ce que la
source change sans que cela signifie quelque chose — ordre des champs, champ qu'aucun
template ne lit, horodatage d'émission. Hacher la source ferait réécrire toute la table à
chaque envoi, et `modifie_le` ne voudrait plus rien dire.

**Effet de bord assumé** : l'empreinte dépend du template, donc modifier un template
invalide toutes les empreintes de son storage et provoque une réécriture complète au
réimport suivant. C'est traité par un ticket dédié ; ne pas chercher ici à rendre
l'empreinte stable au changement de template.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical(objet: Any) -> bytes:
    """La forme canonique sur laquelle l'empreinte est prise.

    `sort_keys` n'est pas un détail de présentation : c'est lui qui rend l'empreinte
    insensible à l'ordre des clés, et l'ordre des clés d'un objet transformé suit celui
    de la source dès qu'un template recopie un sous-objet entier. Sans lui, le critère 4
    — « une variation non significative de la source ne réécrit rien » — tomberait sur un
    template parfaitement légitime.

    `separators` sans espaces, et `ensure_ascii=False` : la forme ne dépend ni de la
    version de Python ni de la culture. Un accent est encodé en UTF-8 par le `encode`
    ci-dessous, pas en séquence d'échappement.
    """
    return json.dumps(
        objet, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def fingerprint(objet: Any) -> bytes:
    """SHA-256 de la forme canonique, en 32 octets bruts pour la colonne `bytea`.

    SHA-256 et non une somme de contrôle courte : une collision ferait considérer deux
    objets différents comme identiques, donc NE PAS réécrire un objet qui a changé. Le
    défaut serait silencieux et sans date — `modifie_le` n'aurait pas bougé non plus.
    """
    return hashlib.sha256(canonical(objet)).digest()
