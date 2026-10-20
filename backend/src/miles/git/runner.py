from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from miles.git.forge import TOKEN_USERNAME
from miles.secrets.model import Secret

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


async def run_git(args: list[str], cwd: Path, token: Secret) -> GitResult:
    """Lance git sans terminal, sans configuration de la machine, jeton par l'environnement."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "LC_ALL": "C",
        # Point d'injection du jeton : déballé ici seulement.
        "MILES_GIT_TOKEN": token.reveal(),
    }
    command = [
        "git",
        # Vide d'abord tout helper hérité, puis pose le nôtre.
        "-c",
        "credential.helper=",
        "-c",
        f"credential.helper={_CREDENTIAL_HELPER}",
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
    return GitResult(process.returncode or 0, _scrub(stdout, token), _scrub(stderr, token))


def _scrub(output: bytes, token: Secret) -> str:
    # git ne recopie pas le mot de passe, mais une forge pourrait le renvoyer en écho :
    # il ne doit jamais remonter vers un message ou un journal.
    text = output.decode("utf-8", "replace")
    secret = token.reveal()
    return text.replace(secret, "********") if secret else text
