"""Le code d'appariement : un TOTP (RFC 6238) dérivé du secret d'UNE demande.

Pourquoi un TOTP plutôt qu'un code aléatoire à usage unique : c'est le choix de Gael du
26/10/2026, et il tient à l'affichage. Un code aléatoire doit être stocké pour être
comparé et reste affichable indéfiniment ; un TOTP se recalcule, se renouvelle tout seul
sous les yeux de l'humain, et une capture d'écran oubliée cesse de valoir quelque chose
après une fenêtre. Le secret, lui, ne quitte jamais la base de ce module.

Ce code reste DANS le produit, et ce n'est pas un oubli : il n'a qu'un usage aujourd'hui.
La règle du dépôt est d'extraire au socle quand un second usage apparaît — l'enrôlement
d'un device en aura un, et il sera dans ce produit lui aussi.

Écart assumé avec le TOTP des applications d'authentification : SHA-256 et non SHA-1.
Aucun humain ne configure ce secret dans une application tierce — il lit un code sur un
écran de Miles — donc l'interopérabilité ne coûte rien ici, et SHA-1 n'a pas à être
réintroduit dans le dépôt pour une compatibilité dont personne ne se sert.
"""

from __future__ import annotations

import base64
import hmac
import os
import struct
from datetime import datetime
from hashlib import sha256

# 30 secondes : la durée que tout le monde connaît, et qui laisse le temps de lire un code
# sur un onglet et de le coller dans un autre.
STEP_S = 30
DIGITS = 6
_SECRET_BYTES = 20
# Fenêtre courante ET précédente, pas davantage (ticket 6a0daab6) : copier un code d'un
# onglet à l'autre prend quelques secondes, et une tolérance plus large allongerait la vie
# du secret sans rendre le geste plus réaliste.
ACCEPTED_OFFSETS = (0, -1)
# Portée de la recherche employée UNIQUEMENT pour le diagnostic d'horloge : ±10 minutes.
# Elle n'accepte rien — elle permet de dire « ce code était bon, il y a N fenêtres », ce
# qui désigne l'horloge au lieu de laisser chercher du côté du code. Un appariement TOTP
# qui échoue sans dire pourquoi est le piège classique de ce protocole.
DRIFT_SEARCH_WINDOWS = 20


def new_totp_secret() -> str:
    """Un secret par demande, et jamais rien de permanent.

    Un code dérivé d'un secret permanent côté module d'enrôlement admettrait n'importe
    quel environnement qui le présenterait ; un secret lié à une demande ne vaut que pour
    celle-là. Rendu en base64url parce que c'est sous cette forme qu'il est chiffré et
    rangé, le dispositif des secrets ne transportant que du texte.
    """
    return base64.urlsafe_b64encode(os.urandom(_SECRET_BYTES)).decode("ascii").rstrip("=")


def totp_code(secret: str, at: datetime) -> str:
    """Le code de la fenêtre qui contient `at`. C'est lui qui s'affiche à l'humain."""
    return _code_at_counter(secret, _counter(at))


def seconds_remaining(at: datetime) -> int:
    """Ce qui reste de la fenêtre courante, pour que l'écran puisse l'afficher.

    Sans cette valeur, l'humain ne sait pas s'il lui reste 29 secondes ou une, et colle un
    code périmé dont le refus ressemble à un code faux.
    """
    return STEP_S - int(at.timestamp()) % STEP_S


def resolve_code_offset(secret: str, code: str, at: datetime) -> int | None:
    """La fenêtre, relative à `at`, où ce code est le bon. `None` si aucune ne l'est.

    Rend un DÉCALAGE et non un booléen, parce que l'appelant a deux décisions à prendre
    avec : accepter (décalage dans `ACCEPTED_OFFSETS`) et diagnostiquer (décalage trouvé
    mais hors des fenêtres acceptées ⇒ les horloges des deux serveurs divergent). Les
    fondre en un booléen rendrait le second message impossible à écrire.
    """
    if len(code) != DIGITS or not code.isdigit():
        return None
    courant = _counter(at)
    # Les fenêtres acceptées sont essayées EN PREMIER : le cas nominal ne dépend pas de la
    # portée de la recherche de dérive, qu'on peut donc élargir sans rien ralentir.
    for offset in (*ACCEPTED_OFFSETS, *_drift_offsets()):
        if hmac.compare_digest(_code_at_counter(secret, courant + offset), code):
            return offset
    return None


def _drift_offsets() -> tuple[int, ...]:
    return tuple(
        offset
        for offset in range(-DRIFT_SEARCH_WINDOWS, DRIFT_SEARCH_WINDOWS + 1)
        if offset not in ACCEPTED_OFFSETS
    )


def _counter(at: datetime) -> int:
    return int(at.timestamp()) // STEP_S


def _code_at_counter(secret: str, counter: int) -> str:
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", counter), sha256).digest()
    # Troncature dynamique de la RFC 4226 : les quatre bits de poids faible du dernier
    # octet désignent où lire les quatre octets du code. Le bit de poids fort est masqué
    # pour que le nombre soit positif quelle que soit l'implémentation qui le relit.
    offset = digest[-1] & 0x0F
    (value,) = struct.unpack(">I", digest[offset : offset + 4])
    return str((value & 0x7FFFFFFF) % (10**DIGITS)).zfill(DIGITS)


def _decode_secret(secret: str) -> bytes:
    padded = secret + "=" * (-len(secret) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))
