from __future__ import annotations

import base64
import binascii
import hashlib
import re

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

# Deux en-têtes, et non un seul : l'origine est une DONNÉE de l'appel — elle entre dans
# ce qui est signé — tandis que la signature est son enveloppe.
ORIGIN_HEADER = "X-Miles-Origin"
SIGNATURE_HEADER = "X-Miles-Signature"
# Version dans l'en-tête ET dans la chaîne canonique. Dans l'en-tête, elle permet de
# refuser proprement un format qu'on ne sait pas lire ; dans la chaîne signée, elle
# interdit qu'une signature produite pour la v1 soit resservie comme signature d'une v2
# dont la canonicalisation différerait — une attaque par changement de version.
VERSION = "v1"
_CANONICAL_PREFIX = f"miles-call-{VERSION}"
# Une origine est une entrée non authentifiée tant que la signature n'est pas vérifiée :
# bornée et validée avant tout usage, journalisation comprise.
MAX_ORIGIN_LENGTH = 200
_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.-]{1,180}(:[0-9]{2,5})?$")


class CallSignatureError(ValueError):
    """Appel signé refusé. `reason` est un code destiné au JOURNAL, jamais à la réponse HTTP.

    Ce que l'appelant apprend se limite à « refusé » : lui dire si c'est l'en-tête, la
    forme, l'origine ou la signature qui pèche lui offrirait un oracle pour approcher
    l'une par l'autre.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"signature refusée : {reason}")
        self.reason = reason


def canonical_bytes(*, method: str, target: str, origin: str, body: bytes) -> bytes:
    """Ce qui est RÉELLEMENT signé : la méthode, la cible, l'origine et l'empreinte du corps.

    Séparateur « \\n » et champs d'un seul tenant : aucun des quatre ne peut contenir de
    retour à la ligne (la méthode et la cible viennent du protocole HTTP, l'origine est
    validée par `_ORIGIN_RE`, l'empreinte est hexadécimale). Sans cette garantie, un champ
    porteur du séparateur permettrait de déplacer la frontière entre deux champs et de
    faire signer autre chose que ce qu'on croit — la confusion de confinement classique.

    Le corps entre par son empreinte et non en entier : une charge de plusieurs mégaoctets
    n'a pas à être recopiée en mémoire pour être signée.

    LIMITE ASSUMÉE, et ce n'est pas un oubli : cette signature lie le CONTENU de l'appel,
    pas son INSTANT. Rejouée telle quelle, elle reste valide. L'horodatage, le nonce et
    l'anti-rejeu sont l'objet du ticket « Enveloppe d'appel à usage unique, message
    rejouable », qui s'applique aux trois modules et ajoutera ses champs à cette chaîne —
    d'où la version, qui existe pour que ce jour-là rien d'ancien ne reste acceptable.
    """
    digest = hashlib.sha256(body).hexdigest()
    return "\n".join((_CANONICAL_PREFIX, method.upper(), target, origin, digest)).encode("utf-8")


def sign_call(
    private_key: Ed25519PrivateKey, *, origin: str, method: str, target: str, body: bytes
) -> str:
    """Valeur de l'en-tête de signature, à poser telle quelle sur la requête sortante."""
    validate_origin(origin)
    signature = private_key.sign(
        canonical_bytes(method=method, target=target, origin=origin, body=body)
    )
    return f"{VERSION} {base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"


def verify_call(
    public_key: Ed25519PublicKey,
    header: str | None,
    *,
    origin: str,
    method: str,
    target: str,
    body: bytes,
) -> None:
    """Vérifie l'appel entrant, ou lève. L'absence d'en-tête est un refus, pas un passe-droit."""
    if not header:
        raise CallSignatureError("absente")
    parts = header.split()
    if len(parts) != 2:
        raise CallSignatureError("forme_invalide")
    version, encoded = parts
    if version != VERSION:
        raise CallSignatureError("version_inconnue")
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        signature = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError):
        raise CallSignatureError("forme_invalide") from None
    try:
        public_key.verify(
            signature, canonical_bytes(method=method, target=target, origin=origin, body=body)
        )
    except InvalidSignature:
        raise CallSignatureError("signature_invalide") from None


def validate_origin(origin: str) -> str:
    """Une origine http(s) sans chemin, bornée. Lève pour toute autre forme."""
    if not _ORIGIN_RE.match(origin) or len(origin) > MAX_ORIGIN_LENGTH:
        raise CallSignatureError("origine_invalide")
    return origin


def origin_for_log(raw: str | None) -> str:
    """L'origine déclarée, telle qu'on peut la JOURNALISER avant toute vérification.

    Le journal doit nommer l'origine d'un appel refusé — c'est tout ce qu'on a pour
    retrouver qui frappe. Mais cette origine arrive d'un en-tête que personne n'a encore
    authentifié : la recopier telle quelle écrirait dans nos journaux ce qu'un inconnu a
    choisi d'y mettre. Elle est donc validée, et remplacée par une marque si elle ne tient
    pas la forme attendue.
    """
    if raw is None or raw == "":
        return "(absente)"
    try:
        return validate_origin(raw)
    except CallSignatureError:
        return "(origine_invalide)"


async def post_signed(
    http: httpx.AsyncClient,
    private_key: Ed25519PrivateKey,
    *,
    origin: str,
    contact_url: str,
    path: str,
    body: bytes,
) -> httpx.Response:
    """L'appel sortant signé : le seul endroit du projet qui en compose un.

    Au socle depuis le 29/10/2026, parce qu'un DEUXIÈME produit en a besoin — le module
    d'enrôlement, qui doit prévenir une stack qu'il lui révoque l'accès, après le module
    d'environnement qui appelle son pair. Un produit, on laisse chez lui ; deux, on extrait.

    `origin` et `contact_url` sont deux choses, et c'est le cœur de cette fonction :

    - `origin` est l'adresse publique CONFIGURÉE de l'émetteur, celle qui entre dans la
      chaîne signée. Jamais lue d'un en-tête, qu'un `Host` forgé suffirait à tromper.
    - `contact_url` est l'adresse que l'on COMPOSE. Elle n'entre dans AUCUNE signature :
      la chaîne porte l'origine de l'émetteur, la méthode, le chemin et l'empreinte du
      corps — jamais l'hôte appelé. C'est ce qui permet de joindre un pair derrière un
      intermédiaire sans toucher ni aux clés ni aux origines.

    `contact_url` est une origine SANS chemin : la cible signée et le chemin de la requête
    coïncident donc, condition pour que le pair vérifie exactement la chaîne qu'on a signée.
    """
    entete = sign_call(private_key, origin=origin, method="POST", target=path, body=body)
    return await http.post(
        f"{contact_url}{path}",
        content=body,
        headers={
            ORIGIN_HEADER: origin,
            SIGNATURE_HEADER: entete,
            "Content-Type": "application/json",
        },
    )
