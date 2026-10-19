from __future__ import annotations

import fcntl
import os
import re
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import BinaryIO

ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ENV_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
# Valeur écrite entre apostrophes : docker compose n'y interpole pas les `$`, que
# porte toute empreinte argon2id. Une apostrophe ou un saut de ligne dans la
# valeur casserait le fichier, d'où le refus en amont.
_SAFE_VALUE_RE = re.compile(r"^[^'\n\r]*$")


class EnvFileError(Exception):
    """Le fichier .env est illisible, mal formé, ou ne peut pas être écrit."""


class EnvEntriesPresentError(EnvFileError):
    """Une entrée qu'on voulait ajouter existe déjà : on n'écrase jamais."""


def file_read_env(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EnvFileError(f"{path} illisible ({type(exc).__name__})") from exc
    return parse_env(text, path)


def parse_env(text: str, path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(stripped)
        if match is None:
            # Le numéro de ligne, jamais son contenu : elle peut porter un secret.
            raise EnvFileError(f"{path} ligne {number} mal formée")
        entries[match.group(1)] = _unquote(match.group(2))
    return entries


def _unquote(raw: str) -> str:
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    return raw


def render_entries(entries: Mapping[str, str]) -> bytes:
    lines = []
    for key, value in entries.items():
        if not ENV_KEY_RE.match(key) or not _SAFE_VALUE_RE.match(value):
            raise ValueError(f"entrée {key} impossible à écrire dans .env")
        lines.append(f"{key}='{value}'\n")
    return "".join(lines).encode("utf-8")


def file_append_entries(
    env_path: Path,
    backup_path: Path,
    entries: Mapping[str, str],
    refuse_if_present: Collection[str],
) -> None:
    """Ajoute des entrées à `.env` après l'avoir sauvegardé dans `.env.bak`.

    `.env` et `.env.bak` sont montés fichier par fichier dans le conteneur
    (décision du 19/10/2026). Écrire un temporaire puis le renommer échouerait
    (EBUSY) ou n'atteindrait pas l'hôte : on écrit donc EN PLACE, et c'est
    `.env.bak`, écrit d'abord, qui permet de restaurer après une interruption.
    """
    payload = render_entries(entries)
    try:
        with env_path.open("r+b") as env:
            # Verrou entre processus : la lecture « aucun compte » et l'ajout
            # doivent être indivisibles, sinon deux amorçages simultanés passent.
            fcntl.flock(env, fcntl.LOCK_EX)
            original = env.read()
            present = parse_env(original.decode("utf-8"), env_path).keys() & set(refuse_if_present)
            if present:
                raise EnvEntriesPresentError(f"déjà présent dans .env : {sorted(present)}")
            _file_overwrite_in_place(backup_path, original)
            env.seek(0, os.SEEK_END)
            # Ajouter sans réécrire : les autres entrées restent intactes à l'octet près.
            if original and not original.endswith(b"\n"):
                env.write(b"\n")
            env.write(payload)
            _sync(env)
    except UnicodeDecodeError as exc:
        raise EnvFileError(f"{env_path} illisible ({type(exc).__name__})") from exc
    except FileNotFoundError as exc:
        raise EnvFileError(
            f"{exc.filename} absent : dev-deploy.sh le crée avant le démarrage"
        ) from exc


def _file_overwrite_in_place(path: Path, content: bytes) -> None:
    # "r+b" et non "wb" : le fichier doit exister (il est monté) ; le créer ici
    # le créerait dans le conteneur, hors de l'hôte, et la sauvegarde serait perdue.
    with path.open("r+b") as backup:
        backup.truncate(0)
        backup.write(content)
        _sync(backup)


def _sync(handle: BinaryIO) -> None:
    handle.flush()
    os.fsync(handle.fileno())
