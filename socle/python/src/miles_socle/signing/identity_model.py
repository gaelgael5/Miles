"""Ce qu'est l'identité d'un module, et les refus qu'elle peut opposer.

Séparé du service pour que le magasin puisse en dépendre sans dépendre du service — et
pour qu'un produit qui ne veut que la forme n'entraîne pas asyncpg et httpx derrière elle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from miles_socle.signing.peers import IdentityError

# La ligne unique de `module_identity` : une seule valeur est admise par la contrainte de
# la base, et c'est elle. Le modèle, et non le code, interdit la seconde.
SINGLETON = "self"
# Slug du secret qui porte la clé privée. Constant et non configurable : c'est l'identité
# du module, pas une préférence d'exploitation, et un slug variable rendrait la ligne
# `module_identity` d'une installation illisible par l'outillage d'une autre.
SIGNING_KEY_SLUG = "identite-du-module"
SIGNING_KEY_TYPE = "MODULE_SIGNING_KEY"
# L'usage déclaré du secret. Il ne sert pas à documenter : c'est lui qui fait refuser la
# suppression du secret par le socle, avec un 409 qui nomme le consommateur, au lieu de
# laisser l'écran des secrets buter sur la clé étrangère et rendre une erreur de serveur.
SIGNING_KEY_CONSUMER_KIND = "module_identity"
# Type d'event écrit à la naissance de l'identité. Chaque produit l'ajoute à son catalogue :
# le journal refuse un type inconnu, et c'est voulu.
IDENTITY_CREATED_EVENT = "module.identity_created"
EVENT_TYPES = frozenset({IDENTITY_CREATED_EVENT})


class IdentityMissingError(IdentityError):
    """Aucune identité en base. Le module n'a pas encore démarré sur cette base."""


class IdentityInconsistentError(IdentityError):
    """La clé privée rangée ne correspond PAS à la clé publique déclarée.

    État anormal, et qui ne se répare pas tout seul : la clé publique est celle que le
    pair détient, donc signer avec une autre privée produirait des appels refusés chez
    lui, sans que rien ici ne soit rouge. On refuse de signer, bruyamment.

    Comment y arrive-t-on : la valeur du secret a été remplacée par l'écran générique des
    secrets, qui ne connaît pas la portée de ce qu'il remplace. Une régénération, elle,
    passe par la rotation de l'appariement, pas par là.
    """


class IdentitySlugTakenError(IdentityError):
    """Un secret porte déjà le slug de l'identité, alors que le module n'en a pas.

    L'écran générique des secrets admet n'importe quel slug. Adopter en silence un secret
    dont on ne sait rien reviendrait à signer avec une valeur posée par quelqu'un d'autre ;
    tomber sur une violation d'unicité donnerait une erreur de serveur illisible. On refuse
    donc en nommant la cause et le geste qui la répare.
    """


class OriginMissingError(IdentityError):
    """Le module ne connaît pas sa propre adresse publique, et ne peut donc pas signer.

    L'origine entre dans ce qui est signé. Elle est CONFIGURÉE (MILES_PUBLIC_URL), jamais
    lue des en-têtes de la requête : un `Host` forgé ferait signer pour une autre origine
    que la sienne, et le pair enregistrerait cette origine comme la nôtre.
    """


@dataclass(frozen=True)
class ModuleIdentity:
    """Ce que le module peut montrer de son identité : tout, sauf la clé privée."""

    public_key: str
    algorithm: str
    created_at: datetime
