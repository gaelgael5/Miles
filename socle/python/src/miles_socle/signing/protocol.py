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

from pydantic import BaseModel, ConfigDict, Field, SecretStr

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


# L'ESPÈCE du demandeur, déclarée en frappant (ticket ba44914b). Deux espèces aujourd'hui,
# et accepter l'une ou l'autre n'a pas les mêmes conséquences : un environnement reçoit des
# devices, le module de paramétrage se fait confier des connexions git. C'est pour cela
# qu'elle VOYAGE, au lieu d'être devinée du nom déclaré ou de l'URL.
#
# ELLE EST DÉCLARÉE, DONC ELLE N'AUTORISE RIEN. Comme le nom déclaré, elle vient d'un tiers
# que personne n'a encore authentifié : ce qu'elle fait, c'est permettre à l'humain de
# l'enrôlement de lire ce qu'il s'apprête à accepter. L'autorisation, c'est son geste à
# lui — révéler le code —, et la conséquence de l'espèce (recevoir des devices, se voir
# confier des secrets git) est appliquée APRÈS, à partir de l'espèce enregistrée. Un
# demandeur qui mentirait sur son espèce obtiendrait donc exactement ce qu'un humain aura
# accepté de donner à cette URL-là, sous ce nom-là, après l'avoir lu.
PeerSpecies = Literal["environnement", "parametrage"]
# Ce que signifie l'ABSENCE du champ : un demandeur d'avant l'espèce, donc un
# environnement — c'était la seule espèce qui existât. Ce n'est pas un repli de confort,
# c'est la lecture exacte d'une demande ouverte avant le 29/10/2026, et c'est ce qui
# évite de rompre le contrat pour un champ ajouté.
DEFAULT_PEER_SPECIES: PeerSpecies = "environnement"


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
    # Absente, elle vaut « environnement » : voir `DEFAULT_PEER_SPECIES`. Facultative
    # plutôt qu'obligatoire parce qu'un champ ajouté ne doit pas faire refuser en 422 une
    # demande que le module d'enrôlement sait parfaitement lire.
    species: PeerSpecies = DEFAULT_PEER_SPECIES


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


# Les connexions git que le module de PARAMÉTRAGE confie au module d'ENRÔLEMENT (ticket
# edcf78bc). Servie par l'ENRÔLEMENT, appelée par le PARAMÉTRAGE — même sens que les
# quatre premières routes.
#
# POURQUOI LE PARAMÉTRAGE POUSSE, ET NON L'ENRÔLEMENT QUI INTERROGE. Le ticket laissait le
# sens libre. C'est le module de paramétrage qui SAIT quand une valeur change, et c'est lui
# qui détient le clair : poussant, il transmet au moment du changement. Si l'enrôlement
# interrogeait, il faudrait qu'il sache quand demander — donc qu'il demande périodiquement,
# donc qu'il tienne pour vrai, entre deux interrogations, un credential déjà remplacé —, et
# toute lecture de git dépendrait de la disponibilité du module de paramétrage. Le sens
# retenu est aussi celui des rôles déjà posés : l'enrôlement SERT les routes, les autres
# les APPELLENT.
GIT_CONNECTIONS_PATH = "/api/peer/git-connections"
# Bornes GROSSIÈRES de ce qui voyage, volontairement plus larges que les règles de chaque
# base — qui sont à elles, pas au contrat. Elles existent pour qu'une charge démesurée ne
# soit ni interprétée ni écrite chez le destinataire, rien de plus.
MAX_CONFIDED_CONNECTIONS = 500
MAX_CONFIDED_WORKSPACES = 2000
MAX_CONNECTION_ID_LENGTH = 200
MAX_CONNECTION_LABEL_LENGTH = 800
MAX_FORGE_URL_LENGTH = 400
MAX_CREDENTIAL_LENGTH = 16 * 1024


class ConfidedWorkspace(BaseModel):
    """Un workspace qui se sert de cette connexion, et le dépôt qu'il travaille.

    Le DÉPÔT est ici et non sur la connexion parce qu'il est au workspace : une connexion
    porte la forge ou une organisation, et chaque workspace y choisit son dépôt. Les deux
    voyagent ensemble parce que lire git pour un environnement demande les deux, et que
    séparer les deux moitiés en deux messages ferait tenir une jointure au destinataire.

    `repo_url` est NUL pour un workspace dont le dépôt n'est pas encore configuré. Il
    voyage quand même : l'omettre ferait diverger en silence la liste que l'enrôlement
    affiche de celle que le module de paramétrage montre, et personne ne saurait lequel
    des deux a raison.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=MAX_CONNECTION_ID_LENGTH)
    repo_url: str | None = Field(default=None, max_length=MAX_FORGE_URL_LENGTH)


class ConfidedGitConnection(BaseModel):
    """Une connexion git confiée : la forge, le credential, et qui s'en sert.

    Rien de plus que ces champs, et c'est une décision du ticket : « chaque champ ajouté
    ici devient un champ à tenir synchronisé entre deux bases que personne ne réconcilie ».

    Le credential est un `SecretStr` : sa représentation textuelle est masquée, donc une
    charge journalisée par mégarde — ou un modèle affiché dans une trace — ne révèle rien.
    C'est la même règle que le `Secret` du socle, appliquée au bord du réseau.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=MAX_CONNECTION_ID_LENGTH)
    label: str = Field(max_length=MAX_CONNECTION_LABEL_LENGTH)
    base_url: str = Field(max_length=MAX_FORGE_URL_LENGTH)
    credential: SecretStr = Field(max_length=MAX_CREDENTIAL_LENGTH)
    workspaces: tuple[ConfidedWorkspace, ...] = Field(
        default=(), max_length=MAX_CONFIDED_WORKSPACES
    )


class ConfideGitConnectionsIn(BaseModel):
    """L'ÉTAT COMPLET des connexions git, pas un écart.

    POURQUOI L'ÉTAT ET NON UN ÉCART. Un écart exige un ordre, un accusé et une file à
    rejouer : un message perdu laisse les deux bases durablement différentes, et rien ne le
    dit. L'état converge de lui-même — une transmission manquée est réparée par la
    suivante — et la SUPPRESSION d'une connexion n'a pas de message à elle : absente de
    l'état, elle est détruite chez le destinataire (critère 9 du ticket edcf78bc).

    `revision` est strictement croissante, allouée par le module de paramétrage au moment
    où il lit son état. Elle existe pour qu'une transmission ancienne arrivée en retard —
    deux administrateurs qui changent deux connexions en même temps — ne vienne pas
    écraser une plus récente. Le destinataire refuse une révision inférieure à celle qu'il
    détient, et le dit : accepter silencieusement l'ancienne ferait croire au module de
    paramétrage que ce qu'il voit est ce que l'autre détient.
    """

    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    connections: tuple[ConfidedGitConnection, ...] = Field(max_length=MAX_CONFIDED_CONNECTIONS)


class ConfideGitConnectionsOut(BaseModel):
    """Ce que le destinataire rend : la révision qu'il détient désormais, et ce qu'il a fait.

    Les comptes ne sont pas décoratifs : ils sont ce que l'écran du module de paramétrage
    affiche pour dire « confiées » sans avoir à croire sa propre intention. `destroyed`
    compte les connexions qui ont disparu de l'état — c'est la seule trace de la
    suppression, qui n'a pas de message à elle.
    """

    model_config = ConfigDict(extra="forbid")

    revision: int
    held: int
    destroyed: int
