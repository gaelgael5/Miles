from __future__ import annotations

import hmac
from collections.abc import Mapping
from hashlib import sha256

# Contrat globals « Contrat OBO » v6 (d0e2dad3), figé : en-têtes, charge canonique et
# fenêtre sont ceux de `portal/mcp/obo.py`, à l'octet près. Ne rien « améliorer » ici :
# une sérialisation différente casse l'interopérabilité sans erreur visible.
ACTOR_HEADER = "x-portal-actor"
TIMESTAMP_HEADER = "x-portal-actor-timestamp"
SIGNATURE_HEADER = "x-portal-actor-signature"
REPLAY_WINDOW_S = 300


def sign_actor(actor: str, timestamp: int, secret: str) -> str:
    return hmac.new(secret.encode(), f"{actor}\n{timestamp}".encode(), sha256).hexdigest()


def signed_actor(headers: Mapping[str, str], key: str, now_s: float) -> str | None:
    """L'acteur, si sa signature par la clé présentée est valide et récente ; None sinon.

    Repli voulu, jamais un refus : sans acteur valide, l'appel reste celui de la clé
    (contrat : « jamais 401 pour ça »). Le secret est la clé de la requête elle-même.
    """
    actor = headers.get(ACTOR_HEADER, "").strip()
    raw_timestamp = headers.get(TIMESTAMP_HEADER, "").strip()
    signature = headers.get(SIGNATURE_HEADER, "").strip()
    if not actor or not raw_timestamp or not signature or not raw_timestamp.isdigit():
        return None
    timestamp = int(raw_timestamp)
    if abs(now_s - timestamp) > REPLAY_WINDOW_S:
        return None
    if not hmac.compare_digest(sign_actor(actor, timestamp, key), signature.lower()):
        return None
    return actor
