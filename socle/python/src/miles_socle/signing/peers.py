"""Formes communes aux deux bouts d'un appariement : clé publique et origine d'un pair.

Au socle depuis le 28/10/2026, parce qu'un DEUXIÈME produit en a besoin — le module
d'enrôlement, qui enregistre N environnements, après le module d'environnement, qui
enregistre son unique module d'enrôlement. Les deux doivent admettre exactement les mêmes
formes : une clé que l'un accepte et que l'autre refuse rendrait l'appariement impossible
dans un sens sur deux, et le diagnostic partirait sur la signature.
"""

from __future__ import annotations

import re

from miles_socle.signing.keys import ALGORITHM

# 43 caractères : base64url sans rembourrage de 32 octets. La même expression est écrite
# dans les CHECK des migrations des deux produits — la base est le dernier mot, celle-ci
# refuse avant d'écrire pour que l'erreur nomme le champ plutôt qu'une contrainte.
PUBLIC_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
# Origine http(s) SANS chemin : c'est elle qui entre dans la chaîne signée de chaque appel.
# Un chemin la rendrait ambiguë — deux écritures de la même origine ne signeraient plus
# la même chaîne, et la vérification échouerait sans que rien ne soit faux.
BASE_URL_RE = re.compile(r"^https?://[A-Za-z0-9.-]{1,180}(:[0-9]{2,5})?$")
MAX_BASE_URL_LENGTH = 200
# Nom déclaré d'un module : assez pour « Environnement de recette — région nord », trop
# peu pour qu'un tiers remplisse un écran ou un journal avec sa prose.
MAX_DECLARED_NAME_LENGTH = 80


class IdentityError(Exception):
    """Base des refus liés à l'identité et aux pairs. Aucun message ne porte de clé privée."""


class IdentityInputError(IdentityError):
    """Saisie refusée ; `field` nomme le champ fautif."""

    def __init__(self, field: str) -> None:
        super().__init__(f"champ invalide : {field}")
        self.field = field


def validate_public_key(public_key: str) -> str:
    """Forme de la clé publique telle qu'elle est stockée : base64url de 32 octets.

    Vérifier la FORME ne vérifie pas que le pair détient la clé privée correspondante —
    `Ed25519PublicKey.from_public_bytes` accepte 32 octets quelconques (mesuré le
    28/10/2026). C'est le premier appel signé qui le prouve, jamais l'enregistrement : d'où
    la demande d'appariement qui est elle-même signée par la clé qu'elle dépose.
    """
    if not PUBLIC_KEY_RE.match(public_key):
        raise IdentityInputError("public_key")
    return public_key


def validate_base_url(base_url: str) -> str:
    """Origine http(s) sans chemin. Entrée utilisateur : validée avant tout usage en URL."""
    base_url = base_url.strip().rstrip("/")
    if len(base_url) > MAX_BASE_URL_LENGTH or not BASE_URL_RE.match(base_url):
        raise IdentityInputError("base_url")
    return base_url


def validate_algorithm(algorithm: str) -> str:
    # Une seule valeur admise aujourd'hui, et la base le contraint aussi. Le champ existe
    # pour que les lignes déjà écrites disent ce qui les a signées le jour où il y en a deux.
    if algorithm != ALGORITHM:
        raise IdentityInputError("algorithm")
    return algorithm


def validate_declared_name(name: str) -> str:
    """Nettoie un nom déclaré par un tiers NON ENCORE AUTHENTIFIÉ.

    Trois gestes, et pas un de plus :

    - les espaces de bord disparaissent, parce que le nom arrive par un formulaire ;
    - les caractères de CONTRÔLE sont refusés — un retour à la ligne casse une ligne de
      journal structuré, et `\0` tronque silencieusement dans certaines couches ;
    - la longueur est bornée.

    Ce qui n'est délibérément PAS fait : retirer les chevrons, les guillemets ou ce qui
    ressemble à du balisage. L'échappement appartient à l'affichage, qui sait dans quel
    contexte il écrit ; le faire ici mutilerait un nom légitime tout en donnant
    l'illusion d'une protection — et le jour où un écran oublierait d'échapper, personne
    ne le verrait puisque « c'est déjà nettoyé ».
    """
    name = name.strip()
    # `isprintable` est vrai pour l'espace et pour les lettres accentuées, faux pour les
    # tabulations, les retours à la ligne et les caractères de contrôle : c'est exactement
    # la coupure voulue, et elle n'a pas à être réécrite en expression régulière.
    if not name or len(name) > MAX_DECLARED_NAME_LENGTH or not name.isprintable():
        raise IdentityInputError("name")
    return name
