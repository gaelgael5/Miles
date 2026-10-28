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

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from miles_socle.signing.peers import MAX_DECLARED_NAME_LENGTH

# Échange de vivacité entre deux modules appariés, dans un sens comme dans l'autre.
PEER_PING_PATH = "/api/peer/ping"
# Appariement : l'environnement frappe, puis confirme avec le code recopié par l'humain.
# Les deux routes sont servies par le module d'ENRÔLEMENT et appelées par l'ENVIRONNEMENT.
PAIRING_REQUEST_PATH = "/api/peer/pairing/request"
PAIRING_CONFIRM_PATH = "/api/peer/pairing/confirm"
# L'environnement demande où en est SA demande. Il ne peut pas le déduire de ses
# propres échanges : un code refusé et une demande disparue rendent le même refus
# opaque, et sans cette route un écran afficherait « en attente » pour toujours.
PAIRING_STATUS_PATH = "/api/peer/pairing/status"
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
    """Ce que l'environnement dépose en frappant : sa clé publique et son nom déclaré.

    Son origine n'est PAS dans le corps : elle est déjà dans l'en-tête d'origine, qui
    entre dans la chaîne signée. L'y remettre créerait deux sources pour la même valeur,
    dont une seule serait couverte par la signature.

    Rien de plus que ces deux champs. Chaque champ ajouté ici est un champ à maintenir
    synchronisé entre deux bases que personne ne réconcilie.
    """

    model_config = ConfigDict(extra="forbid")

    public_key: str
    # Texte libre d'un tiers NON ENCORE AUTHENTIFIÉ : il sert à ce qu'un humain
    # reconnaisse la demande qu'il accepte, et n'identifie rien. Deux demandes peuvent
    # porter le même, et c'est l'URL qui les distingue. Échappé à l'affichage.
    #
    # La borne ici est GROSSIÈRE et volontairement plus large que la règle : elle interdit
    # qu'une charge démesurée soit interprétée, rien de plus. La vraie règle — 80
    # caractères, pas de caractère de contrôle — est appliquée par
    # `validate_declared_name`, qui refuse en NOMMANT le champ. Borner au plus juste ici
    # ferait refuser une saisie de 81 caractères sur « corps invalide », message qui
    # n'apprend rien à qui doit corriger sa saisie.
    name: str = Field(max_length=MAX_DECLARED_NAME_LENGTH * 4)


class PairingRequestOut(BaseModel):
    """L'accusé de la demande : elle existe, elle attend un humain, et elle expirera."""

    model_config = ConfigDict(extra="forbid")

    base_url: str
    expires_at: str


class PairingConfirmIn(BaseModel):
    """Le code recopié par l'humain depuis l'écran du module d'enrôlement."""

    model_config = ConfigDict(extra="forbid")

    code: str


class PairingStatusOut(BaseModel):
    """Où en est la demande de l'appelant, vue par le module d'enrôlement.

    Deux états seulement, et c'est volontaire : « en attente », ou « inconnue ». Le module
    d'enrôlement ne garde aucune trace d'une demande refusée ou expirée — une pierre
    tombale par tentative serait un état de plus à purger, et dirait à qui frappe au
    hasard si une origine a déjà été refusée.

    C'est l'APPELANT qui tranche entre « refusée » et « expirée », en comparant à
    l'échéance qu'il a reçue en frappant : inconnue avant l'échéance, un humain a refusé ;
    inconnue après, elle a expiré. Il détient les deux moitiés, le pair n'en détient qu'une.
    """

    model_config = ConfigDict(extra="forbid")

    state: Literal["en_attente", "inconnue"]
    expires_at: str | None


class PairingConfirmOut(BaseModel):
    """La moitié que le module d'enrôlement rend : son origine et sa clé publique.

    Aucune clé privée ne figure ici, et il n'en existe aucun champ — dans aucun sens, y
    compris « pour simplifier le premier appariement ».
    """

    model_config = ConfigDict(extra="forbid")

    base_url: str
    public_key: str
    algorithm: str
