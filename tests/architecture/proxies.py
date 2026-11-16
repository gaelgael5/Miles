"""Les trois proxies de façade compressent-ils toujours ce qu'ils servent ?

`frontend/nginx.conf` ne se partage pas entre les produits — celui du portail diverge de
34 lignes des autres — et ce qui se partage, c'est la GARDE. Celle-ci encode une panne
mesurée le 15/11/2026 : les trois configurations ne portaient aucune directive de
compression, et le bundle du portail partait à 823 Kio même quand le navigateur annonçait
`gzip`. Invisible depuis la machine, où le fichier sort en 2 ms, et payé en entier sur le
lien de la personne.

C'est la troisième fois que `LESSONS.md` porte la même famille : une propriété déclarée
seulement dans le proxy, qu'aucun test ne regarde (02/11/2026, un 405 rendu par nginx avec
191 tests verts ; 07/11/2026, une borne de corps absente du dépôt). La corriger sans poser
la garde garantirait qu'elle revienne au prochain fichier de configuration écrit.

Les fichiers sont LUS, jamais exécutés : il n'y a pas de nginx dans la suite de tests, et
ce qu'on protège est la déclaration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

PRODUITS = ("portail", "enrolement", "environnement")
NGINX_CONF = "frontend/nginx.conf"

# Les types que les trois façades servent et qui gagnent à être compressés. Les actifs déjà
# compressés — images, polices — n'y sont pas : les recomprimer coûte du processeur pour un
# résultat parfois plus gros, et le ticket 89965957 l'interdit explicitement.
TYPES_ATTENDUS = ("application/javascript", "text/css", "application/json", "image/svg+xml")

_GZIP_ON = re.compile(r"^\s*gzip\s+on\s*;", re.MULTILINE)
_GZIP_TYPES = re.compile(r"^\s*gzip_types\s(?P<liste>[^;]*);", re.MULTILINE | re.DOTALL)


@dataclass(frozen=True)
class Manque:
    """Ce qui manque à une façade, et de quoi le lecteur a besoin pour le réparer."""

    fichier: str
    raison: str

    def __str__(self) -> str:
        return f"{self.fichier} : {self.raison}"


def file_compression(conf: Path) -> tuple[str, ...]:
    """Les types déclarés compressés par cette configuration, ou () si elle ne compresse pas.

    `gzip on` sans `gzip_types` ne couvre que text/html : c'est une compression déclarée qui
    laisserait partir le bundle entier, donc elle ne compte pas comme telle.
    """
    texte = conf.read_text(encoding="utf-8")
    # Les commentaires d'abord : une directive NOMMÉE dans une explication n'est pas posée,
    # et ce fichier-ci en nomme plusieurs.
    actif = "\n".join(ligne.split("#")[0] for ligne in texte.splitlines())
    if not _GZIP_ON.search(actif):
        return ()
    declares = _GZIP_TYPES.search(actif)
    return tuple(declares["liste"].split()) if declares else ()


def resolve_facades_sans_compression(depot: Path) -> tuple[Manque, ...]:
    manques = []
    for produit in PRODUITS:
        conf = depot / produit / NGINX_CONF
        if not conf.is_file():
            manques.append(Manque(f"{produit}/{NGINX_CONF}", "configuration de façade absente"))
            continue
        types = file_compression(conf)
        if not types:
            manques.append(
                Manque(
                    f"{produit}/{NGINX_CONF}",
                    "aucune compression déclarée : le bundle partirait en entier sur le lien"
                    " de la personne (mesuré à 823 Kio le 15/11/2026)",
                )
            )
            continue
        absents = [t for t in TYPES_ATTENDUS if t not in types]
        if absents:
            manques.append(
                Manque(f"{produit}/{NGINX_CONF}", f"types non compressés : {', '.join(absents)}")
            )
    return tuple(manques)
