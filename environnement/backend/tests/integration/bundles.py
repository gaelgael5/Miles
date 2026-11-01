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


def bundle_substitue(tmp_path: Path, number: int, sur_commit: str) -> bytes:
    """Un bundle dont `version/<number>` EXISTE mais pointe sur `sur_commit`.

    C'est la SUBSTITUTION RÉELLE, et elle ne se confond pas avec un bundle qui ne porte
    pas la bonne étiquette : celui-là échoue dès la récupération, sur « couldn't find
    remote ref », et n'atteint jamais la comparaison de commit. Mesuré le 01/11/2026 — un
    premier essai de ce test construisait le cas faible et validait donc le mauvais refus.

    Ce qu'un intermédiaire ferait, lui, c'est servir un contenu qui a l'air du bon : la
    bonne étiquette, un autre arbre. Seul le commit, qui voyage dans l'ordre SIGNÉ, permet
    de le refuser.

    Travaille sur le dépôt que `fabrique` a laissé dans `tmp_path` : les deux vont
    ensemble, et appeler celui-ci sans celle-là n'a pas de sens.
    """
    depot = tmp_path / "depot"
    git("tag", "-d", f"version/{number}", cwd=depot)
    git(*AUTHOR, "tag", "-a", f"version/{number}", sur_commit, "-m", "Substituée", cwd=depot)
    paquet = tmp_path / f"substitue-{number}.bundle"
    git("bundle", "create", str(paquet), f"version/{number}", cwd=depot)
    return paquet.read_bytes()
