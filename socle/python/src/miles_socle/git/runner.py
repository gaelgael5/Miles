"""Lancer git sans terminal et sans jamais exposer le jeton, au socle depuis le 01/11/2026.

Deuxième usage avec le module d'enrôlement. C'est la pièce qu'il fallait le moins
réécrire : le jeton n'apparaît ni dans les arguments — `ps auxww` les voit —, ni sur
disque, ni dans la sortie rendue, et chacune de ces trois garanties tient à une ligne
précise ci-dessous. Une seconde implémentation en aurait perdu une sans le dire.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from miles_socle.git.access import GitAccess
from miles_socle.git.forge import TOKEN_USERNAME

# Une forge lente ne doit pas retenir l'administrateur indéfiniment sur le test.
GIT_TIMEOUT_S = 60.0
COMMITTER_NAME = "Miles back-office"
COMMITTER_EMAIL = "miles@back-office.invalid"
# Le jeton n'apparaît jamais dans les arguments (lisibles par `ps`) ni sur disque : git
# le demande à ce petit helper, qui le lit dans l'environnement du seul processus git.
_CREDENTIAL_HELPER = (
    f'!f() {{ echo "username={TOKEN_USERNAME}"; echo "password=$MILES_GIT_TOKEN"; }}; f'
)


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


async def run_git(args: list[str], cwd: Path, access: GitAccess | None = None) -> GitResult:
    """Lance git sans terminal, sans configuration de la machine, jeton par l'environnement.

    `access` NUL n'est pas un repli : c'est le cas du module d'environnement, qui lance
    git pour ouvrir un bundle et poser un arbre, et qui ne détient AUCUN credential —
    c'est l'interdit central du ticket edcf78bc. Aucun assistant d'identifiants n'est
    alors posé, et aucune variable ne porte de jeton : un git qui serait malgré tout
    envoyé vers une forge échouerait faute d'identifiants, au lieu d'en trouver un.
    """
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LC_ALL": "C",
    }
    # Vide d'abord tout helper hérité — dans les DEUX cas, et c'est ce qui garantit
    # qu'un git lancé sans credential n'en trouve pas un dans la configuration de la
    # machine. Le helper qui lit le jeton n'est posé que s'il y a un jeton.
    options = ["-c", "credential.helper="]
    if access is not None:
        # Point d'injection du jeton : déballé ici seulement.
        env["MILES_GIT_TOKEN"] = access.token.reveal()
        options += ["-c", f"credential.helper={_CREDENTIAL_HELPER}"]
    command = [
        "git",
        *options,
        # git 2.39 (Debian bookworm) échoue par intermittence contre GitHub en HTTP/2 :
        # défaut mesuré, consigné dans la skill test-machine-deployment.
        "-c",
        "http.version=HTTP/1.1",
        "-c",
        f"user.name={COMMITTER_NAME}",
        "-c",
        f"user.email={COMMITTER_EMAIL}",
        *args,
    ]
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), GIT_TIMEOUT_S)
    except TimeoutError:
        process.kill()
        await process.wait()
        return GitResult(124, "", "délai dépassé")
    return GitResult(process.returncode or 0, _scrub(stdout, access), _scrub(stderr, access))


def _scrub(output: bytes, access: GitAccess | None) -> str:
    # git ne recopie pas le mot de passe, mais une forge pourrait le renvoyer en écho :
    # il ne doit jamais remonter vers un message ou un journal. Sans jeton, il n'y a rien
    # à masquer — et surtout rien à masquer par erreur : remplacer la chaîne vide
    # découperait toute la sortie.
    text = output.decode("utf-8", "replace")
    if access is None:
        return text
    secret = access.token.reveal()
    return text.replace(secret, "********") if secret else text
