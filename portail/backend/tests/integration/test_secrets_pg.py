from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from structlog.testing import capture_logs

from miles.events.model import EventAuthor, EventError, EventTypeCatalog
from miles.secrets.crypto import SecretCipher
from miles.secrets.model import (
    Consumer,
    SecretNotFoundError,
    SecretTypeMismatchError,
    SecretUndecipherableError,
)
from miles.secrets.service import (
    EVENT_TYPES,
    SecretsService,
    resolve_attach_secret,
    resolve_detach_secret,
)
from tests.integration.portal_stack import open_portal_stack, utc_now

pytestmark = pytest.mark.integration

# Valeurs discriminantes : on les cherche ensuite partout où elles ne doivent pas être.
VALUE = "ghp_valeur-du-jeton-a-ne-jamais-revoir"
OTHER_VALUE = "valeur-de-remplacement-tout-aussi-secrete"
AUTHOR = EventAuthor("local", "admin")
GIT = {"slug": "git-token", "label": "Jeton GitHub", "secret_type": "GIT_TOKEN", "value": VALUE}


_now = utc_now


@dataclass
class Stack:
    pool: asyncpg.Pool
    service: SecretsService
    client: httpx.AsyncClient
    app: FastAPI


@pytest.fixture
async def stack(blank_db: str, tmp_path: Path) -> AsyncIterator[Stack]:
    async with open_portal_stack(blank_db, tmp_path) as portal:
        service = SecretsService(
            portal.pool, SecretCipher(os.urandom(32)), EventTypeCatalog(EVENT_TYPES), _now
        )
        portal.app.state.secrets = service
        yield Stack(portal.pool, service, portal.client, portal.app)


async def _create(stack: Stack, **overrides: str) -> httpx.Response:
    return await stack.client.post("/api/secrets", json={**GIT, **overrides})


async def test_created_secret_is_listed_without_value_and_stored_encrypted(stack: Stack) -> None:
    created = await _create(stack)
    listed = await stack.client.get("/api/secrets")
    detail = await stack.client.get("/api/secrets/git-token")

    assert created.status_code == 201
    assert created.json()["slug"] == "git-token"
    assert listed.json()[0]["label"] == "Jeton GitHub"
    assert detail.json()["secret_type"] == "GIT_TOKEN"
    for response in (created, listed, detail):
        assert VALUE not in response.text
    row = await stack.pool.fetchrow("SELECT * FROM secrets WHERE slug = 'git-token'")
    assert VALUE.encode() not in b"".join(v for v in row.values() if isinstance(v, bytes))
    assert VALUE not in str(dict(row))
    assert (await stack.service.resolve_secret("git-token")).reveal() == VALUE


async def test_resolution_needs_no_session_and_checks_the_expected_type(stack: Stack) -> None:
    await _create(stack)

    secret = await stack.service.resolve_secret("git-token", expected_type="GIT_TOKEN")

    assert VALUE not in repr(secret) and VALUE not in str(secret)
    with pytest.raises(SecretTypeMismatchError):
        await stack.service.resolve_secret("git-token", expected_type="OIDC_CLIENT_SECRET")
    with pytest.raises(SecretNotFoundError, match="absent"):
        await stack.service.resolve_secret("absent")


async def test_type_catalogue_is_served_and_enforced(stack: Stack) -> None:
    types = (await stack.client.get("/api/secret-types")).json()["types"]
    refused = await _create(stack, secret_type="API_KEY")

    assert "GIT_TOKEN" in types and "OIDC_CLIENT_SECRET" in types
    assert refused.status_code == 422
    assert refused.json()["detail"] == {"field": "secret_type"}


async def test_list_filtered_by_type_returns_only_that_type(stack: Stack) -> None:
    await _create(stack)
    await _create(stack, slug="oidc-kc", secret_type="OIDC_CLIENT_SECRET", label="Keycloak")

    oidc = await stack.client.get("/api/secrets", params={"secret_type": "OIDC_CLIENT_SECRET"})

    assert [s["slug"] for s in oidc.json()] == ["oidc-kc"]


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"slug": "Bad Slug"}, "slug"),
        ({"slug": "a"}, "slug"),
        ({"label": "  "}, "label"),
        ({"secret_type": "git"}, "secret_type"),
        ({"value": ""}, "value"),
        ({"value": "${local://git-token}"}, "value"),
        ({"value": VALUE * 1000}, "value"),
    ],
)
async def test_invalid_creation_names_the_field_and_stores_nothing(
    stack: Stack, overrides: dict[str, str], field: str
) -> None:
    response = await _create(stack, **overrides)

    assert response.status_code == 422
    assert response.json()["detail"] == {"field": field}
    assert VALUE not in response.text
    assert await stack.pool.fetchval("SELECT count(*) FROM secrets") == 0
    assert await stack.pool.fetchval("SELECT count(*) FROM events") == 0


async def test_taken_slug_is_refused(stack: Stack) -> None:
    await _create(stack)

    again = await _create(stack, label="Autre")

    assert again.status_code == 409
    assert again.json()["detail"] == "slug_pris"


async def test_replaced_value_is_served_and_the_old_one_is_gone(stack: Stack) -> None:
    await _create(stack)
    before = await stack.pool.fetchrow("SELECT nonce, ciphertext FROM secrets")

    response = await stack.client.put("/api/secrets/git-token/value", json={"value": OTHER_VALUE})

    assert response.status_code == 204
    assert (await stack.service.resolve_secret("git-token")).reveal() == OTHER_VALUE
    after = await stack.pool.fetchrow("SELECT nonce, ciphertext FROM secrets")
    assert after["ciphertext"] != before["ciphertext"]
    missing = await stack.client.put("/api/secrets/absent/value", json={"value": OTHER_VALUE})
    assert missing.status_code == 404


async def test_relabel_changes_the_label_only(stack: Stack) -> None:
    await _create(stack)

    response = await stack.client.patch(
        "/api/secrets/git-token", json={"label": "Compte de service"}
    )

    assert response.json()["label"] == "Compte de service"
    assert (await stack.service.resolve_secret("git-token")).reveal() == VALUE


async def test_ciphertext_copied_onto_another_secret_does_not_open(stack: Stack) -> None:
    await _create(stack)
    await _create(stack, slug="oidc-kc", secret_type="OIDC_CLIENT_SECRET", value=OTHER_VALUE)
    await stack.pool.execute(
        "UPDATE secrets SET nonce = g.nonce, ciphertext = g.ciphertext"
        " FROM (SELECT nonce, ciphertext FROM secrets WHERE slug = 'git-token') g"
        " WHERE slug = 'oidc-kc'"
    )

    with pytest.raises(SecretUndecipherableError):
        await stack.service.resolve_secret("oidc-kc")


async def test_reading_with_another_key_fails_explicitly(stack: Stack) -> None:
    await _create(stack)
    other = SecretsService(
        stack.pool, SecretCipher(os.urandom(32)), EventTypeCatalog(EVENT_TYPES), _now
    )

    with pytest.raises(SecretUndecipherableError):
        await other.resolve_secret("git-token")


async def test_secret_in_use_cannot_be_deleted_and_lists_its_consumers(stack: Stack) -> None:
    await _create(stack)
    consumer = Consumer("workspace", "ws-1")
    async with stack.pool.acquire() as conn, conn.transaction():
        await resolve_attach_secret(conn, "git-token", "GIT_TOKEN", consumer)
        await resolve_attach_secret(conn, "git-token", "GIT_TOKEN", consumer)  # rejeu

    refused = await stack.client.delete("/api/secrets/git-token")
    detail = await stack.client.get("/api/secrets/git-token")

    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "secret_utilise",
        "consumers": [{"kind": "workspace", "id": "ws-1"}],
    }
    assert detail.json()["consumers"] == [{"kind": "workspace", "id": "ws-1"}]
    async with stack.pool.acquire() as conn:
        await resolve_detach_secret(conn, "git-token", consumer)
    assert (await stack.client.delete("/api/secrets/git-token")).status_code == 204
    assert (await stack.client.get("/api/secrets/git-token")).status_code == 404


async def test_attach_checks_existence_and_type_at_configuration_time(stack: Stack) -> None:
    await _create(stack)
    async with stack.pool.acquire() as conn:
        with pytest.raises(SecretNotFoundError):
            await resolve_attach_secret(conn, "absent", "GIT_TOKEN", Consumer("workspace", "w"))
        with pytest.raises(SecretTypeMismatchError):
            await resolve_attach_secret(
                conn, "git-token", "OIDC_CLIENT_SECRET", Consumer("oidc.connector", "kc")
            )
    assert await stack.pool.fetchval("SELECT count(*) FROM secret_usages") == 0


async def test_database_itself_refuses_deleting_a_used_secret(stack: Stack) -> None:
    # Filet sous la vérification applicative : la clé étrangère RESTRICT tient seule.
    await _create(stack)
    async with stack.pool.acquire() as conn, conn.transaction():
        await resolve_attach_secret(conn, "git-token", "GIT_TOKEN", Consumer("workspace", "w"))

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await stack.pool.execute("DELETE FROM secrets WHERE slug = 'git-token'")


async def test_every_change_writes_an_event_that_never_carries_the_value(stack: Stack) -> None:
    await _create(stack)
    await stack.client.put("/api/secrets/git-token/value", json={"value": OTHER_VALUE})
    await stack.client.patch("/api/secrets/git-token", json={"label": "Renommé"})
    await stack.client.delete("/api/secrets/git-token")

    rows = await stack.pool.fetch(
        "SELECT e.type, e.author_directory, e.author_subject, e.properties::text AS props"
        " FROM events e JOIN event_objects o ON o.event_id = e.id"
        " WHERE o.object_kind = 'secret' AND o.object_id = 'git-token' ORDER BY o.sequence"
    )

    assert [r["type"] for r in rows] == [
        "secret.created",
        "secret.value_replaced",
        "secret.relabeled",
        "secret.deleted",
    ]
    assert {(r["author_directory"], r["author_subject"]) for r in rows} == {("local", "admin")}
    for row in rows:
        assert VALUE not in row["props"] and OTHER_VALUE not in row["props"]
        json.loads(row["props"])


async def test_event_failure_fails_the_creation(stack: Stack) -> None:
    refusing = SecretsService(stack.pool, stack.service.cipher, EventTypeCatalog(), _now)

    with pytest.raises(EventError):
        await refusing.resolve_create(AUTHOR, "git-token", "Jeton", "GIT_TOKEN", VALUE)

    assert await stack.pool.fetchval("SELECT count(*) FROM secrets") == 0


async def test_logs_never_contain_the_value_even_on_error_paths(stack: Stack) -> None:
    with capture_logs() as logs:
        await _create(stack)
        await _create(stack)  # slug pris
        await _create(stack, slug="autre-secret", value="${" + VALUE + "}")
        await stack.client.put("/api/secrets/git-token/value", json={"value": OTHER_VALUE})
        async with stack.pool.acquire() as conn, conn.transaction():
            await resolve_attach_secret(conn, "git-token", "GIT_TOKEN", Consumer("workspace", "w"))
        await stack.client.delete("/api/secrets/git-token")
        await stack.pool.execute("UPDATE secrets SET ciphertext = ciphertext || '\\x00'::bytea")
        with pytest.raises(SecretUndecipherableError):
            await stack.service.resolve_secret("git-token")

    text = repr(logs)
    assert "secret_cree" in text and "secret_indechiffrable" in text
    assert VALUE not in text and OTHER_VALUE not in text


async def test_secret_routes_require_a_session(stack: Stack) -> None:
    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=stack.app), base_url="http://miles"
    )
    async with anonymous:
        for method, path in [
            ("GET", "/api/secrets"),
            ("POST", "/api/secrets"),
            ("GET", "/api/secrets/git-token"),
            ("DELETE", "/api/secrets/git-token"),
            ("GET", "/api/secret-types"),
        ]:
            response = await anonymous.request(method, path, json=GIT)
            assert response.status_code == 401, (method, path)
    assert await stack.pool.fetchval("SELECT count(*) FROM secrets") == 0
