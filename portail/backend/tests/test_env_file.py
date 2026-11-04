from __future__ import annotations

import stat
from pathlib import Path

import pytest
from miles_socle.auth.env_file import (
    EnvEntriesPresentError,
    EnvFileError,
    file_append_entries,
    file_read_env,
    parse_env,
    render_entries,
)

from tests.auth_fixtures import BASE_ENV, write_env

HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA"


def test_parse_env_skips_comments_and_blank_lines_and_unquotes() -> None:
    text = "# commentaire\n\nA_KEY=plain\nB_KEY='$quoted$'\nC_KEY=\"dq\"\nD_KEY=\n"

    entries = parse_env(text, Path(".env"))

    assert entries == {"A_KEY": "plain", "B_KEY": "$quoted$", "C_KEY": "dq", "D_KEY": ""}


def test_parse_env_malformed_line_raises_without_leaking_content() -> None:
    with pytest.raises(EnvFileError, match="ligne 2 mal formée") as caught:
        parse_env("A=1\nMILES_ADM s3cr3t\n", Path(".env"))

    assert "s3cr3t" not in str(caught.value)


def test_file_read_env_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(EnvFileError, match="illisible"):
        file_read_env(tmp_path / "absent")


def test_render_entries_refuses_quote_or_newline_in_value() -> None:
    with pytest.raises(ValueError, match="MILES_X"):
        render_entries({"MILES_X": "it's"})
    with pytest.raises(ValueError, match="MILES_Y"):
        render_entries({"MILES_Y": "a\nb"})


def test_render_entries_refuses_invalid_key() -> None:
    with pytest.raises(ValueError, match="lower"):
        render_entries({"lower": "x"})


def test_append_entries_keeps_existing_bytes_and_writes_backup(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path)

    file_append_entries(env, backup, {"MILES_ADMIN_PASSWORD_HASH": HASH}, ["MILES_ADMIN_EMAIL"])

    content = env.read_bytes()
    assert content.startswith(BASE_ENV.encode())
    assert backup.read_text(encoding="utf-8") == BASE_ENV
    assert file_read_env(env)["MILES_ADMIN_PASSWORD_HASH"] == HASH
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_append_entries_writes_in_place_keeping_inode(tmp_path: Path) -> None:
    # Un fichier monté seul est lié à son inode : le remplacer couperait l'hôte.
    env, backup = write_env(tmp_path)
    inode, backup_inode = env.stat().st_ino, backup.stat().st_ino

    file_append_entries(env, backup, {"MILES_K": "v"}, [])

    assert env.stat().st_ino == inode
    assert backup.stat().st_ino == backup_inode


def test_append_entries_adds_newline_when_file_lacks_one(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path, "MILES_A=1")

    file_append_entries(env, backup, {"MILES_B": "2"}, [])

    assert file_read_env(env) == {"MILES_A": "1", "MILES_B": "2"}


def test_append_entries_refuses_when_key_already_present(tmp_path: Path) -> None:
    env, backup = write_env(tmp_path, BASE_ENV + "MILES_ADMIN_EMAIL='a@b.fr'\n")
    before = env.read_bytes()

    with pytest.raises(EnvEntriesPresentError):
        file_append_entries(env, backup, {"MILES_ADMIN_EMAIL": "x@y.fr"}, ["MILES_ADMIN_EMAIL"])

    assert env.read_bytes() == before
    assert backup.read_text(encoding="utf-8") == ""


def test_append_entries_without_backup_file_raises_and_leaves_env_untouched(
    tmp_path: Path,
) -> None:
    env, backup = write_env(tmp_path)
    backup.unlink()

    with pytest.raises(EnvFileError, match=r"\.env\.bak absent"):
        file_append_entries(env, backup, {"MILES_K": "v"}, [])

    assert env.read_text(encoding="utf-8") == BASE_ENV
    assert not backup.exists()
