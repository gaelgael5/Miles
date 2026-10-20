from __future__ import annotations

import pytest

from miles.git.forge import RepositoryUrlError, parse_repository


@pytest.mark.parametrize(
    ("raw", "url"),
    [
        ("https://github.com/Acme/Config", "https://github.com/acme/config.git"),
        ("https://github.com/acme/config.git", "https://github.com/acme/config.git"),
        ("  https://GitHub.com/acme/config/  ", "https://github.com/acme/config.git"),
        ("https://github.com/a_b/c.d-e", "https://github.com/a_b/c.d-e.git"),
    ],
)
def test_github_urls_are_normalised(raw: str, url: str) -> None:
    assert parse_repository(raw).url == url


@pytest.mark.parametrize(
    "raw",
    [
        "http://github.com/acme/config",
        "https://gitlab.com/acme/config",
        "https://user:pw@github.com/acme/config",
        "https://github.com/acme/config?x=1",
        "https://github.com/acme",
        "https://github.com/acme/config/tree/main",
        "https://github.com/../etc",
        "git@github.com:acme/config.git",
        "https://github.com/acme/con fig",
        "file:///tmp/repo",
    ],
)
def test_anything_but_a_plain_github_repository_is_refused(raw: str) -> None:
    with pytest.raises(RepositoryUrlError):
        parse_repository(raw)


def test_test_host_is_admitted_only_when_declared() -> None:
    raw = "http://forge:3000/miles/cfg.git"

    assert parse_repository(raw, ["forge:3000"]).url == raw
    with pytest.raises(RepositoryUrlError):
        parse_repository(raw)
