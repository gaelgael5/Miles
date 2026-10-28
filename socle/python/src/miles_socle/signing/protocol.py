"""Le contrat d'appel entre modules : chemins et formes, écrits UNE fois pour les deux bouts.

Ce fichier n'est pas une commodité. Les chemins entrent dans la chaîne canonique signée :
l'émetteur et le vérificateur doivent en avoir la même idée AU CARACTÈRE PRÈS, sinon la
signature est refusée sans que rien ne soit faux de part ni d'autre — et le diagnostic
part sur les clés. Deux constantes de même valeur dans deux produits auraient divergé au
premier renommage fait d'un seul côté ; une seule les rend inséparables.

Même raison pour `PongOut` : le module qui sert l'échange et celui qui lit sa réponse
décrivent le même contrat. Deux modèles de même forme auraient divergé au premier champ
ajouté d'un seul côté, et le second l'aurait ignoré en silence.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# Échange de vivacité entre deux modules appariés, dans un sens comme dans l'autre.
PEER_PING_PATH = "/api/peer/ping"
# Appariement : l'environnement frappe, puis confirme avec le code recopié par l'humain.
# Les deux routes sont servies par le module d'ENRÔLEMENT et appelées par l'ENVIRONNEMENT.
PAIRING_REQUEST_PATH = "/api/peer/pairing/request"
PAIRING_CONFIRM_PATH = "/api/peer/pairing/confirm"
# Corps de l'échange de vivacité. Vide de sens, mais pas vide : son empreinte entre dans
# la signature, donc il doit être identique des deux côtés.
PING_BODY = b"{}"


class PongOut(BaseModel):
    """Réponse de l'échange de vivacité, servie par l'un et lue par l'autre."""

    model_config = ConfigDict(extra="forbid")

    module: str
    # L'adresse publique de CELUI QUI RÉPOND, pas celle de l'appelant — qui la connaît
    # déjà. Nulle quand MILES_PUBLIC_URL n'est pas configurée ; dans ce cas ce module ne
    # peut pas non plus signer d'appel sortant, et le dire est plus utile qu'une chaîne vide.
    origin: str | None
    # Empreinte de la clé qui a VÉRIFIÉ l'appel, et empreinte de celle du répondant. C'est
    # ce qui rend un désaccord de clés diagnosticable après un ré-appariement : l'appelant
    # compare ce qu'il croit détenir à ce que le pair a réellement employé.
    verified_key_fingerprint: str
    own_key_fingerprint: str


class PairingRequestIn(BaseModel):
    """Ce que l'environnement dépose en frappant : sa clé publique, et rien d'autre.

    Son origine n'est PAS dans le corps : elle est déjà dans l'en-tête d'origine, qui
    entre dans la chaîne signée. L'y remettre créerait deux sources pour la même valeur,
    dont une seule serait couverte par la signature.
    """

    model_config = ConfigDict(extra="forbid")

    public_key: str


class PairingRequestOut(BaseModel):
    """L'accusé de la demande : elle existe, elle attend un humain, et elle expirera."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    expires_at: str


class PairingConfirmIn(BaseModel):
    """Le code recopié par l'humain depuis l'écran du module d'enrôlement."""

    model_config = ConfigDict(extra="forbid")

    code: str


class PairingConfirmOut(BaseModel):
    """La moitié que le module d'enrôlement rend : son origine et sa clé publique.

    Aucune clé privée ne figure ici, et il n'en existe aucun champ — dans aucun sens, y
    compris « pour simplifier le premier appariement ».
    """

    model_config = ConfigDict(extra="forbid")

    base_url: str
    public_key: str
    algorithm: str
