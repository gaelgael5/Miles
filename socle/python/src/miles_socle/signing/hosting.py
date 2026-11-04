"""Le contrat de l'hébergement d'une version de workspace par un environnement.

Deux routes, écrites UNE fois pour les deux bouts, pour exactement la raison de
`protocol.py` : les chemins entrent dans la chaîne canonique signée, et deux constantes de
même valeur dans deux produits auraient divergé au premier renommage fait d'un seul côté —
la signature serait alors refusée sans que rien ne soit faux de part ni d'autre, et le
diagnostic partirait sur les clés.

Fichier à part de `protocol.py`, et non une section de plus : celui-là porte
l'APPARIEMENT, celui-ci l'hébergement, et le premier atteint déjà la limite de 300 lignes
du dépôt.

**LE SENS DES DEUX ROUTES EST UN CHOIX**, pas une symétrie (Gael, 01/11/2026) :
l'enrôlement POUSSE l'ordre — « sers la version 7, commit `<sha>` » —, et l'environnement
VIENT CHERCHER le contenu. Les deux conséquences qui ont décidé ce sens : l'environnement
se répare seul après un redémarrage ou une perte de disque, sans geste humain ni rien à
relancer en face ; et l'ordre reste un petit message, là où un dépôt entier ne tiendrait
pas dans un appel qui peut expirer.

**CE QUI NE VOYAGE JAMAIS ICI : le credential git.** L'environnement ne tire pas chez la
forge, il tire chez l'enrôlement, qui détient le secret pour son compte — c'est le relais
que le ticket `edcf78bc` avait reporté, et l'interdit est tenu par
`tests/architecture/test_credentials.py`. Les noms de CE fichier ne sont volontairement
PAS dans la liste de cette garde : ils portent du contenu de dépôt, que le module
d'environnement a le droit de nommer et de demander. Y ajouter `HOSTING_BUNDLE_PATH`
interdirait au destinataire légitime du relais de s'en servir, et le relais n'existerait
plus que sur le papier.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# Servie par l'ENVIRONNEMENT, appelée par l'ENRÔLEMENT. Même sens que l'avis de
# révocation, et c'est le seul autre : l'enrôlement est le seul à savoir qu'un humain
# vient de choisir une version, et l'environnement n'a aucun moyen de l'apprendre seul.
HOSTED_VERSION_PATH = "/api/peer/hosting/version"
# Servie par l'ENRÔLEMENT, appelée par l'ENVIRONNEMENT : le sens de toutes les autres
# routes du protocole. C'est le relais, et il est ici parce que le credential s'arrête
# chez l'enrôlement.
HOSTING_BUNDLE_PATH = "/api/peer/hosting/bundle"

# Bornes GROSSIÈRES de ce qui voyage, volontairement plus larges que les règles de chaque
# base — qui sont à elles, pas au contrat, et que le contrat n'a pas à recopier sous peine
# de refuser demain une valeur que l'une d'elles aura décidé d'accepter.
MAX_HOSTED_WORKSPACE_ID_LENGTH = 200
# Un identifiant de commit COMPLET : un préfixe court ne se récupère pas d'une forge, et
# deux commits pourraient le partager.
COMMIT_PATTERN = r"^[0-9a-f]{40}$"
# Ce qu'on accepte de LIRE en réponse à une demande de bundle, avant même de l'ouvrir : un
# paramétrage est fait de fichiers texte, et une charge démesurée n'a pas à être écrite sur
# le volume d'un environnement pour qu'on découvre ensuite qu'elle n'est pas un bundle.
MAX_BUNDLE_BYTES = 64 * 1024 * 1024
# Récupérer le contenu d'un dépôt ne tient pas dans le délai d'un appel d'administration
# ordinaire (5 s). Cette borne est AU CONTRAT parce que les deux bouts doivent avoir la
# même idée de ce qui est « trop long » : sinon l'un abandonne pendant que l'autre
# travaille encore, et l'administrateur voit un échec là où la version a bel et bien été
# appliquée.
HOSTING_HTTP_TIMEOUT_S = 90.0


class HostedVersionIn(BaseModel):
    """L'ordre : quel workspace, quelle version, et SUR QUEL COMMIT.

    Le commit n'est pas une redondance du numéro : c'est la pièce qui rend l'échange
    vérifiable. Il voyage dans l'ordre, donc DANS la chaîne signée par l'enrôlement, et
    l'environnement refuse ensuite tout bundle dont `version/<n>` ne résout pas exactement
    ce commit. Ce pin est nécessaire parce qu'une RÉPONSE d'appel signé n'est pas signée —
    `post_signed` ne signe que l'aller : sans lui, le contenu qui revient du relais ne
    serait authentifié par rien.

    PAS de libellé. Il s'afficherait joliment, mais c'est une chaîne libre d'un autre
    module, à échapper et à tenir synchronisée entre deux bases que personne ne
    réconcilie ; le numéro, lui, désigne la version sans ambiguïté, et le commit la pin.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(max_length=MAX_HOSTED_WORKSPACE_ID_LENGTH)
    number: int = Field(ge=1)
    commit: str = Field(pattern=COMMIT_PATTERN)


class HostedVersionOut(BaseModel):
    """Ce que l'environnement rend : ce qu'il a ENREGISTRÉ, et ce qu'il SERT réellement.

    Les deux, et jamais l'un seul : « l'ordre est reçu » et « la version est servie » sont
    deux faits distincts, et les confondre ferait afficher « à jour » à un administrateur
    dont l'environnement n'a encore rien appliqué.

    `served_commit` nul veut dire qu'il n'a JAMAIS rien servi de ce workspace. C'est
    distinct d'un commit différent de l'ordonné, qui dit qu'il sert encore la version
    précédente — et le geste à faire n'est pas le même.

    `reason` nomme ce qui a empêché l'application. Un code court et pas un message : il
    traverse vers un écran qui le traduit dans la langue du visiteur.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(max_length=MAX_HOSTED_WORKSPACE_ID_LENGTH)
    ordered_number: int
    ordered_commit: str
    served_commit: str | None
    reason: str | None = Field(default=None, max_length=40)


class HostingBundleIn(BaseModel):
    """Ce que l'environnement demande : le contenu d'UN commit d'UN workspace.

    Il redemande ce qui lui a été ordonné, et l'enrôlement le VÉRIFIE au lieu de le servir
    sur parole : le workspace doit être celui qui est placé sur l'environnement dont la
    signature vient d'être reconnue, et le commit celui qui lui est ordonné. Sans ce
    contrôle, un environnement apparié — donc légitime, mais pour SON workspace — pourrait
    lire le paramétrage de tous les autres.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(max_length=MAX_HOSTED_WORKSPACE_ID_LENGTH)
    commit: str = Field(pattern=COMMIT_PATTERN)
