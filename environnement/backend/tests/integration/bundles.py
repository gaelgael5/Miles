"""Des bundles git fabriqués avec un VRAI git, pour les donner à la contrepartie.

Le socle n'en fabrique pas, et c'est voulu : sa doublure ne fait que SERVIR ce qu'on lui
donne. Ce qu'on éprouve ici est que ce module VÉRIFIE le commit qu'on lui ordonne avant de
poser l'arbre — et ce contrôle ne se vérifie qu'avec des bundles réels, dont l'un porte
délibérément autre chose que ce qu'on annonce.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

AUTHOR = ("-c", "user.name=Alice", "-c", "user.email=alice@annuaire.invalid")


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return out.stdout


@dataclass(frozen=True)
class VersionFabriquee:
    number: int
    commit: str
    bundle: bytes
    # Les fichiers que cette version porte, pour que le test LISE l'arbre posé.
    fichiers: tuple[str, ...]


def fabrique(tmp_path: Path) -> dict[int, VersionFabriquee]:
    """Deux versions : la seconde SUPPRIME un fichier de la première.

    La suppression n'est pas un détail d'essai : un arbre posé par recopie laisserait le
    fichier retiré en place, et la stack servirait un paramétrage que personne n'a publié.
    """
    depot = tmp_path / "depot"
    git("init", "-q", "-b", "main", str(depot))
    (depot / "ecran.json").write_text('{"v": 1}\n', encoding="utf-8")
    git("add", "-A", cwd=depot)
    git(*AUTHOR, "commit", "-q", "-m", "c1", cwd=depot)
    git(*AUTHOR, "tag", "-a", "version/1", "-m", "Première", cwd=depot)
    (depot / "scenario.json").write_text('{"v": 2}\n', encoding="utf-8")
    git("rm", "-q", "ecran.json", cwd=depot)
    git("add", "-A", cwd=depot)
    git(*AUTHOR, "commit", "-q", "-m", "c2", cwd=depot)
    git(*AUTHOR, "tag", "-a", "version/2", "-m", "Réseau ferroviaire", cwd=depot)

    fabriquees: dict[int, VersionFabriquee] = {}
    for number, fichiers in ((1, ("ecran.json",)), (2, ("scenario.json",))):
        paquet = tmp_path / f"v{number}.bundle"
        git("bundle", "create", str(paquet), f"version/{number}", cwd=depot)
        commit = git("rev-parse", f"version/{number}^{{commit}}", cwd=depot).strip()
        fabriquees[number] = VersionFabriquee(number, commit, paquet.read_bytes(), fichiers)
    return fabriquees
