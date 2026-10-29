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


# L'enrôlement prévient l'environnement qu'il lui a RÉVOQUÉ l'accès. Seule route du
# protocole servie par l'ENVIRONNEMENT et appelée par l'ENRÔLEMENT : le sens inverse de
# toutes les autres, et c'est pour cela qu'elle est nommée ici plutôt que déduite.
#
# Elle existe parce que la révocation détruit la clé publique du pair : plus aucune
# signature de lui n'étant vérifiable, répondre « tu es révoqué » à qui DÉCLARE cette
# origine dirait à n'importe quel inconnu qu'une origine a été appariée puis révoquée.
# L'avis poussé lève la contradiction — il est signé par l'enrôlement, et l'environnement
# le vérifie avec une clé qu'il détient déjà.
PAIRING_REVOKED_PATH = "/api/peer/pairing/revoked"
# Corps de l'avis. Vide de sens, pas vide : son empreinte entre dans la signature, donc il
# doit être identique des deux côtés. La DATE n'y figure pas — l'environnement date ce
# qu'il reçoit avec sa propre horloge plutôt que de croire celle d'un autre, les deux
# dérivant (mesuré à l'appariement, où la dérive a son propre refus).
REVOKED_BODY = b"{}"

# L'environnement demande à quel environnement du référentiel l'enrôlement l'a rattaché.
# Servie par l'ENRÔLEMENT, appelée par l'ENVIRONNEMENT, comme les quatre premières.
#
# POURQUOI UNE ROUTE À ELLE, ET PAS UN CHAMP DE PLUS DANS LE PONG. L'échange de vivacité
# est servi par les DEUX modules avec la même forme de réponse, et c'est ce qui permet à
# `PongOut` d'être défini une seule fois ici. L'environnement rattaché, lui, n'existe que
# d'un côté : l'y ajouter ferait porter au pong un champ toujours nul chez l'un des deux
# répondants, et la symétrie qui rend ce modèle partageable serait perdue. Une route de
# plus ne change rien à l'existant ; un champ asymétrique change la lecture des deux.
PEER_ENVIRONMENT_PATH = "/api/peer/environment"
# Corps de la question. Vide de sens, pas vide : son empreinte entre dans la signature.
ENVIRONMENT_BODY = b"{}"
# Bornes GROSSIÈRES de ce qui voyage, volontairement plus larges que la règle du
# référentiel de l'enrôlement — qui est à lui, pas au contrat, et que le contrat n'a pas à
# recopier sous peine de refuser demain un nom qu'il aura décidé d'accepter. Elles
# existent pour qu'une charge démesurée ne soit pas écrite dans la base du consommateur.
MAX_ENVIRONMENT_SLUG_LENGTH = 200
MAX_ENVIRONMENT_LABEL_LENGTH = 400


class AssignedEnvironment(BaseModel):
    """L'environnement du référentiel de l'enrôlement, nommé pour un écran.

    Le SLUG et le LIBELLÉ, jamais l'identifiant. L'identifiant est la clé du référentiel de
    l'enrôlement, et le faire voyager inviterait l'autre bout à s'en servir comme d'une
    référence stable — donc à écrire une relation entre deux bases que personne ne
    réconcilie. Les deux noms voyagent parce qu'ils s'affichent : le libellé se lit, et le
    slug est ce qui s'écrit dans une procédure.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(max_length=MAX_ENVIRONMENT_SLUG_LENGTH)
    label: str = Field(max_length=MAX_ENVIRONMENT_LABEL_LENGTH)


class PeerEnvironmentOut(BaseModel):
    """Réponse de la route ci-dessus : l'environnement rattaché, ou rien.

    Un objet imbriqué plutôt que deux champs plats et nullables : « rattaché ou non » est
    UNE information, et deux champs permettraient d'en rendre une moitié — un slug sans
    libellé — que personne ne saurait afficher.
    """

    model_config = ConfigDict(extra="forbid")

    environment: AssignedEnvironment | None
