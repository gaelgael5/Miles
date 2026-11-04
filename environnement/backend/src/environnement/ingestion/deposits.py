"""Ce que TOUT dépôt vérifie avant de lire quoi que ce soit : l'appelant, et le contenu.

À part des deux services de dépôt — celui des modes synchrones et celui du fichier (story
`0f14adbd`) — parce que ce sont des règles de SÉCURITÉ, et qu'une règle de sécurité en deux
copies est une règle qu'on tiendra d'accord jusqu'au jour où on ne la tiendra plus. Le dépôt
d'un fichier authentifie par ce code avant d'écrire un seul octet sur le disque.
"""

from __future__ import annotations

import structlog
from miles_socle.parametrage.sources import NAME_RE

from environnement.apikeys.model import KeyPrincipal
from environnement.apikeys.service import ApiKeysService
from environnement.ingestion.model import CONTENT_TYPE, FILE_CONTENT_TYPES

log = structlog.get_logger(__name__)


class NotAuthenticated(Exception):
    """Un seul refus pour toutes les raisons : forme, clé inconnue, révoquée, sans octroi.

    Les distinguer offrirait un oracle — savoir qu'une clé existe, ou qu'une source est
    déclarée. La raison précise est au journal, où elle sert au diagnostic.
    """


async def resolve_caller(
    keys: ApiKeysService, source: str, mode: str, presented: str | None
) -> KeyPrincipal:
    """L'appelant, ou un refus unique. **Avant toute lecture de la version servie.**

    Fonction de module et non méthode : le dépôt d'un FICHIER (story 0f14adbd) authentifie
    par le même code, avant d'écrire un seul octet sur le disque. Une seconde copie de
    cette garde aurait été une seconde règle de sécurité à tenir d'accord.
    """
    if not NAME_RE.match(source):
        # Validé avant tout usage en chemin de fichier ou en identifiant. Et refusé
        # comme une clé invalide : un nom mal formé n'apprend rien de plus à
        # l'appelant que « tu n'entres pas ».
        log.info("depot_refuse", raison="source_mal_formee", mode=mode)
        raise NotAuthenticated
    principal = await keys.resolve_authenticate(presented, source)
    if principal is None:
        # La raison précise est déjà au journal, écrite par le vérificateur.
        raise NotAuthenticated
    return principal


def accepts_json(content_type: str | None) -> bool:
    """Le type de contenu attendu, paramètres admis (`; charset=utf-8`).

    Exigé plutôt que deviné : un client qui poste un formulaire ou du XML doit l'apprendre
    de nous, pas d'une erreur d'analyse syntaxique qui parlerait d'une accolade.
    """
    if content_type is None:
        return False
    return content_type.split(";")[0].strip().lower() == CONTENT_TYPE


def accepts_file(content_type: str | None) -> bool:
    """Le type de contenu d'un DÉPÔT DE FICHIER : le JSON, ou un flux d'octets.

    Le flux d'octets est admis en plus, et c'est un écart VOLONTAIRE avec les modes
    synchrones : un partenaire qui pousse un fichier le fait souvent avec un outil qui
    n'annonce rien de mieux qu'`application/octet-stream`, et refuser l'aurait obligé à
    mentir sur son type pour déposer le même document. Le contenu, lui, reste du JSON — et
    c'est le parseur qui le dit, en nommant la position de ce qui ne l'est pas.
    """
    if content_type is None:
        return False
    return content_type.split(";")[0].strip().lower() in FILE_CONTENT_TYPES
