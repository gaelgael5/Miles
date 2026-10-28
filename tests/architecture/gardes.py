"""Les gardes de déploiement sont-elles toujours appelées par les trois produits ?

Chaque garde de `socle/deploy/gardes.sh` encode une panne réelle, et la skill
`test-machine-deployment` le dit sans détour : « n'en retire aucune sans avoir lu la panne
qui l'a motivée », parce que chacune paraît superflue tant qu'on ignore ce qu'elle a coûté.

Le danger propre au partage décidé le 28/10/2026 — gardes au socle, séquence au produit —
est qu'un script cesse d'appeler une garde : elle resterait définie, personne ne la verrait
disparaître, et la panne reviendrait dans ce produit-là seulement. Ce module lit donc les
appels, sans exécuter les scripts : ils arrêtent des stacks et déploient.

La liste est volontairement celle des gardes dont la panne est DOCUMENTÉE, pas l'ensemble de
ce que le socle expose : le jour où une garde ne vaudra que pour deux produits sur trois, il
ne faut pas que ce test l'interdise.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PRODUITS = ("portail", "enrolement", "environnement")
GARDES_SH = "socle/deploy/gardes.sh"
INTEGRATION_SH = "socle/deploy/integration.sh"

# Garde → la panne qui l'a motivée. La raison est ici parce qu'un test qui échoue doit dire
# ce qu'on s'apprête à perdre, pas seulement qu'un nom manque.
GARDES_DU_DEPLOIEMENT = {
    "socle_journal_et_filet": (
        "le script arrête la stack ; lancé depuis une session qu'elle héberge, le SIGHUP "
        "l'a tué entre l'arrêt et le redémarrage — stack à moitié debout, migrations "
        "jamais jouées"
    ),
    "socle_prerequis": (
        "un message « introuvable » sans la commande d'installation impose un aller-retour "
        "à celui qui déploie"
    ),
    "socle_depot_a_jour": (
        "sans ré-exécution, on déploie du code neuf avec un script, un compose et un "
        "Dockerfile périmés"
    ),
    "socle_valeur_durable": (
        "un mot de passe de base régénéré casse la base déjà initialisée, et "
        "MILES_SECRETS_KEY régénérée rend illisibles tous les secrets chiffrés"
    ),
    "socle_port_libre": (
        "sondé AVANT l'arrêt, le port était pris par notre propre service : repli "
        "appliqué à tort, persisté, et tunnel public dans le vide"
    ),
    "socle_conteneur_stable": (
        "un conteneur qui redémarre en boucle fait échouer la migration, le déploiement "
        "avorte avant elle, et la stack sert un schéma en retard sans que rien ne rougisse"
    ),
    "socle_schema_a_jour": (
        "« apply » peut sortir en succès sans avoir atteint la dernière version : on "
        "interroge le résultat, pas le code de retour"
    ),
    "socle_sante": "sans plafond, un service qui ne démarre jamais fait attendre indéfiniment",
    "socle_purge_hebdomadaire": (
        "les couches détaggées saturent le disque, et une machine sans espace ne relance "
        "plus la stack qu'elle vient d'arrêter — en plein déploiement"
    ),
}

GARDES_DE_CAMPAGNE = {
    "socle_it_postgres_pret": (
        "l'entrypoint de postgres:16 lance un serveur temporaire pendant initdb : une "
        "boucle qui sort au premier succès puis repose une seconde sonde a produit sept "
        "échecs « jamais prêt »"
    ),
}


@dataclass(frozen=True)
class GardePerdue:
    produit: str
    script: Path
    garde: str
    panne: str

    def __str__(self) -> str:
        return f"{self.produit} n'appelle plus « {self.garde} » dans {self.script} — {self.panne}"


def file_appels(fichier: Path) -> frozenset[str]:
    """Les noms de gardes du socle appelés par un script, commentaires exclus.

    Les commentaires sont retirés : un script qui se contenterait de NOMMER une garde dans
    une explication ne l'appelle pas, et le test doit voir la différence.
    """
    sans_commentaire = re.sub(r"(?m)^[ \t]*#.*$", "", fichier.read_text(encoding="utf-8"))
    return frozenset(re.findall(r"\bsocle(?:_it)?_[a-z_]+", sans_commentaire))


def resolve_gardes_perdues(depot: Path) -> tuple[GardePerdue, ...]:
    """Les gardes qu'un produit a cessé d'appeler."""
    perdues: list[GardePerdue] = []
    for produit in PRODUITS:
        for relatif, attendues in (
            ("dev-deploy.sh", GARDES_DU_DEPLOIEMENT),
            ("scripts/run-integration-tests.sh", GARDES_DE_CAMPAGNE),
        ):
            script = depot / produit / relatif
            if not script.is_file():
                continue
            appels = file_appels(script)
            perdues.extend(
                GardePerdue(produit, Path(produit) / relatif, garde, panne)
                for garde, panne in attendues.items()
                if garde not in appels
            )
    return tuple(perdues)


def resolve_gardes_non_definies(depot: Path) -> tuple[str, ...]:
    """Les gardes attendues qu'aucun fichier du socle ne définit.

    Garde de la garde : sans elle, renommer une fonction du socle ferait rougir les trois
    produits sans dire que la définition, elle, a changé de nom.
    """
    definies: set[str] = set()
    for relatif in (GARDES_SH, INTEGRATION_SH):
        fichier = depot / relatif
        if fichier.is_file():
            texte = fichier.read_text(encoding="utf-8")
            definies |= set(re.findall(r"(?m)^(socle(?:_it)?_[a-z_]+)\(\)", texte))
    attendues = set(GARDES_DU_DEPLOIEMENT) | set(GARDES_DE_CAMPAGNE)
    return tuple(sorted(attendues - definies))
