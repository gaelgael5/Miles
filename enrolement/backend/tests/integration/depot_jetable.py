"""Un vrai dépôt git, servi en HTTP, le temps d'un test.

**Pourquoi pas une doublure de git.** Ce qu'on vient vérifier ici est précisément ce que
git rend : le format de `for-each-ref`, ce qu'une étiquette annotée porte, ce qu'un bundle
contient. Une doublure rendrait ce qu'on croit — et c'est la croyance qui s'est révélée
fausse le 01/11/2026 sur le bundle d'un dépôt superficiel.

**Pourquoi pas la Gitea jetable du portail.** Sa campagne en lance une parce qu'elle
ÉCRIT sur la forge — elle éprouve cinq droits, pousse des branches et des étiquettes. Ici
on ne fait que LIRE, et le transport HTTP « bêta » de git suffit : mesuré le 01/11/2026,
`ls-remote`, la récupération complète des étiquettes et la fabrication du bundle passent
tous les trois contre un simple serveur de fichiers. Ajouter une Gitea à cette campagne
aurait coûté une image, un provisionnement et un jeton d'administration pour vérifier la
même chose.

Ce transport exige `git update-server-info` après chaque écriture : sans lui, aucun client
ne voit les références, et l'erreur ressemble à un dépôt vide.
"""

from __future__ import annotations

import functools
import http.server
import socketserver
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

OWNER = "proprio"
REPO = "parametrage"
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


@dataclass
class DepotJetable:
    """Le dépôt et son service HTTP. `host` est à passer en hôte git de test."""

    url: str
    host: str
    bare: Path
    seed: Path

    def commits_des_versions(self) -> dict[int, str]:
        """Numéro de version → commit, lu du dépôt lui-même et jamais reconstruit."""
        lignes = git(
            "for-each-ref",
            "--format=%(refname:short) %(*objectname)",
            "refs/tags/version/",
            cwd=self.bare,
        )
        trouves: dict[int, str] = {}
        for ligne in lignes.splitlines():
            nom, _, sha = ligne.partition(" ")
            trouves[int(nom.removeprefix("version/"))] = sha.strip()
        return trouves

    def pose_version(self, number: int, label: str) -> str:
        """Ajoute un commit et son étiquette `version/<n>`, et rend le commit."""
        (self.seed / "f.txt").write_text(f"version {number}\n", encoding="utf-8")
        git("add", "-A", cwd=self.seed)
        git(*AUTHOR, "commit", "-q", "-m", f"c{number}", cwd=self.seed)
        git(*AUTHOR, "tag", "-a", f"version/{number}", "-m", label, cwd=self.seed)
        git("push", "-q", str(self.bare), "HEAD:refs/heads/main", "--tags", cwd=self.seed)
        git("update-server-info", cwd=self.bare)
        return self.commits_des_versions()[number]

    def retire_version(self, number: int) -> None:
        git("push", "-q", str(self.bare), "--delete", f"refs/tags/version/{number}", cwd=self.seed)
        git("update-server-info", cwd=self.bare)


@contextmanager
def depot_jetable(tmp_path: Path, versions: dict[int, str] | None = None) -> Iterator[DepotJetable]:
    """Monte le dépôt, le sert, et arrête tout à la sortie quoi qu'il arrive."""
    racine = tmp_path / "forge"
    bare = racine / OWNER / f"{REPO}.git"
    seed = tmp_path / "semence"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    git("init", "-q", "-b", "main", str(seed))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(racine))
    # Port 0 : le système en attribue un libre. Deux campagnes concurrentes sur la même
    # machine ne doivent pas se disputer un port fixe — c'est la règle de ces suites.
    serveur = socketserver.TCPServer(("127.0.0.1", 0), handler)
    serveur.daemon_threads = True
    port = serveur.server_address[1]
    fil = threading.Thread(target=serveur.serve_forever, daemon=True)
    fil.start()
    hote = f"127.0.0.1:{port}"
    depot = DepotJetable(f"http://{hote}/{OWNER}/{REPO}.git", hote, bare, seed)
    try:
        for number, label in sorted((versions or {}).items()):
            depot.pose_version(number, label)
        yield depot
    finally:
        serveur.shutdown()
        serveur.server_close()
        fil.join(timeout=5)
