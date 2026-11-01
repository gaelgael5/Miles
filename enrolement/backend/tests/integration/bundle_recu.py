"""Ce qu'un module d'environnement fait d'un bundle : aller le chercher, et le VÉRIFIER.

Dans son fichier parce que ce qu'il y a ici est du git, pas du protocole — et parce que la
contrepartie du protocole était à sa limite de 300 lignes.

La vérification du commit est le cœur de l'échange, et c'est pour cela qu'elle est éprouvée
par une contrepartie qui la fait pour de vrai : la réponse du relais n'est pas signée —
`post_signed` ne signe que l'aller —, et c'est l'ORDRE signé qui pin le contenu. Un bundle
qui ne porterait pas exactement le commit ordonné doit être refusé, et ce refus-là ne se
simule pas.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Protocol

import httpx
from miles_socle.signing.hosting import HOSTING_BUNDLE_PATH, HostedVersionIn, HostingBundleIn


class SignedPoster(Protocol):
    """Ce qu'il faut de la contrepartie : savoir poster signé. Rien de son protocole."""

    async def post(self, client: httpx.AsyncClient, path: str, body: bytes) -> httpx.Response: ...


async def applique_bundle(
    double: SignedPoster, ordre: HostedVersionIn, back: httpx.AsyncClient, hosts: Path
) -> tuple[str | None, str | None]:
    """Va chercher le bundle, vérifie le commit ordonné, pose l'arbre. Rend (servi, raison)."""
    corps = HostingBundleIn(workspace_id=ordre.workspace_id, commit=ordre.commit).model_dump_json()
    reponse = await double.post(back, HOSTING_BUNDLE_PATH, corps.encode("utf-8"))
    if reponse.status_code != 200:
        return None, "relais_refuse"
    # Fichiers et git dans un fil : ils bloquent, et cette contrepartie tourne dans la
    # MÊME boucle que le module qu'elle appelle — l'ordre est encore en vol pendant
    # qu'elle travaille. Bloquer la boucle ici figerait les deux.
    return await asyncio.to_thread(_pose, reponse.content, ordre, hosts)


def _pose(paquet_recu: bytes, ordre: HostedVersionIn, hosts: Path) -> tuple[str | None, str | None]:
    hosts.mkdir(parents=True, exist_ok=True)
    paquet = hosts / "version.bundle"
    paquet.write_bytes(paquet_recu)
    copie = hosts / "copie"
    if not (copie / ".git").is_dir():
        git("init", "-q", str(copie))
    ref = f"refs/tags/version/{ordre.number}"
    git("fetch", "-q", str(paquet), f"+{ref}:{ref}", cwd=copie)
    recu = git("rev-parse", f"version/{ordre.number}^{{commit}}", cwd=copie).strip()
    if recu != ordre.commit:
        return None, "commit_inattendu"
    git("-c", "advice.detachedHead=false", "checkout", "-q", recu, cwd=copie)
    return recu, None


def arbre_servi(hosts: Path | None) -> str | None:
    """Le contenu réellement posé, pour que le test le LISE.

    Vérifier que le fichier est là, et avec la bonne valeur, est la seule preuve que le
    paramétrage a traversé : des commits égaux pourraient venir d'un bundle vide.
    """
    if hosts is None:
        return None
    fichier = hosts / "copie" / "f.txt"
    return fichier.read_text(encoding="utf-8") if fichier.is_file() else None


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return out.stdout
