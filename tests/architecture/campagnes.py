"""Une campagne arrêtée doit pouvoir retirer tout ce qu'elle a lancé.

PANNE MESURÉE le 22/11/2026 (bug `db3bccb9`) : le piège de sortie d'une campagne ne
retirait que les conteneurs qu'il pouvait NOMMER. Les conteneurs de test et les sondes
étaient lancés en `docker run --rm` sans `--name`, donc baptisés au hasard par Docker, et
un `kill` du script les laissait tourner — avec le réseau jetable qu'ils retenaient, sur
une machine de test TRANSVERSE.

La correction est au socle (`socle_it_ressources_jetables_retirees`, qui retire par
étiquette). Ce module garde la moitié qui reste chez chaque produit : POSER l'étiquette, et
la poser partout. C'est la seule part où l'oubli est possible, parce qu'elle se répète à
chaque `docker run` — il y en a VINGT ET UN dans les trois campagnes, et le jour où ce
module a été écrit DOUZE n'avaient pas de nom (compté sur `61ea4f5`, le commit d'avant).

On lit les scripts, on ne les exécute pas : ils bâtissent des images et lancent des
conteneurs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PRODUITS = ("portail", "enrolement", "environnement")
SCRIPT = "scripts/run-integration-tests.sh"
# L'étiquette telle que la garde du socle la filtre. Écrite ici en entier, et c'est voulu :
# un test qui ne vérifierait que la présence de `--label` laisserait passer une étiquette
# que `docker ps --filter` ne retrouve pas.
ETIQUETTE = '--label "miles-campagne=$RUN_ID"'
NOM_ATTENDU = '--name "$RUN_ID'


@dataclass(frozen=True)
class LancementSansPrise:
    produit: str
    ligne: int
    commande: str
    manque: str

    def __str__(self) -> str:
        return (
            f"{self.produit}/{SCRIPT}:{self.ligne} — {self.manque} : "
            f"un `docker run` que le piège de sortie ne saura pas retirer\n"
            f"    {self.commande[:120]}"
        )


def file_lancements(fichier: Path) -> tuple[tuple[int, str], ...]:
    """Les `docker run` du script, continuations de ligne recollées, commentaires exclus.

    Recoller les continuations est indispensable : `--name` et `--label` se posent souvent
    sur la deuxième ligne de la commande, et une lecture ligne à ligne les déclarerait
    absents. Les lignes de commentaire sont retirées — un script qui PARLE d'une étiquette
    ne la pose pas.
    """
    lancements: list[tuple[int, str]] = []
    courant: list[str] = []
    debut = 0
    for numero, brute in enumerate(fichier.read_text(encoding="utf-8").splitlines(), start=1):
        ligne = brute.strip()
        if ligne.startswith("#"):
            continue
        if not courant:
            debut = numero
        courant.append(ligne.removesuffix("\\").strip())
        if ligne.endswith("\\"):
            continue
        commande = " ".join(courant)
        courant = []
        if re.search(r"\bdocker run\b", commande):
            lancements.append((debut, commande))
    return tuple(lancements)


def resolve_lancements_sans_prise(depot: Path) -> tuple[LancementSansPrise, ...]:
    """Les `docker run` d'une campagne qu'un piège de sortie ne pourrait pas retirer."""
    anomalies: list[LancementSansPrise] = []
    for produit in PRODUITS:
        script = depot / produit / SCRIPT
        if not script.is_file():
            continue
        for ligne, commande in file_lancements(script):
            for fragment, manque in (
                (NOM_ATTENDU, "aucun nom dérivé de $RUN_ID"),
                (ETIQUETTE, "aucune étiquette miles-campagne=$RUN_ID"),
            ):
                if fragment not in commande:
                    anomalies.append(LancementSansPrise(produit, ligne, commande, manque))
    return tuple(anomalies)
