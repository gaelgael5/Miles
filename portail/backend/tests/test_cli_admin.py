from __future__ import annotations

import io

import pytest

from miles.auth.passwords import verify_password
from miles.cli_admin import EXIT_OK, EXIT_REFUSED, main


def test_hash_password_reads_stdin_and_prints_verifiable_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("une phrase de passe\n"))

    assert main(["hash-password"]) == EXIT_OK

    printed = capsys.readouterr().out.strip()
    assert verify_password(printed, "une phrase de passe")
    assert "une phrase de passe" not in printed


def test_hash_password_weak_password_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("court\n"))

    assert main(["hash-password"]) == EXIT_REFUSED

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "au moins 12" in captured.err
