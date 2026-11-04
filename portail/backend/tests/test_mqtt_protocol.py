from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Any

import pytest

from miles.mqtt.protocol import (
    BUILTIN_HANDLERS,
    Request,
    RequestRejectedError,
    resolve_reply,
    resolve_request,
)
from miles.mqtt.topics import is_allowed_response_topic, parse_request_topic

DEVICE = "term-42"
RESPONSE_TOPIC = f"miles/v1/devices/{DEVICE}/responses/inbox"


def _request(**overrides: Any) -> Request:
    fields: dict[str, Any] = {
        "device": DEVICE,
        "operation": "system.ping",
        "payload": b"\x00opaque\xff",
        "response_topic": RESPONSE_TOPIC,
        "correlation_data": b"\x01\x02\x00\xfe",
    }
    fields.update(overrides)
    return Request(**fields)


def test_parse_request_topic_extracts_device_and_operation() -> None:
    parsed = parse_request_topic(f"miles/v1/devices/{DEVICE}/requests/parcel.lookup")

    assert parsed is not None
    assert (parsed.device, parsed.operation) == (DEVICE, "parcel.lookup")


@pytest.mark.parametrize(
    "topic",
    [
        "miles/v1/devices/term-42/requests",
        "miles/v1/devices/+/requests/x",
        "miles/v1/devices/term-42/requests/a/b",
        "miles/v2/devices/term-42/requests/x",
        "autre/v1/devices/term-42/requests/x",
    ],
)
def test_parse_request_topic_rejects_other_shapes(topic: str) -> None:
    assert parse_request_topic(topic) is None


@pytest.mark.parametrize(
    ("response_topic", "allowed"),
    [
        (RESPONSE_TOPIC, True),
        ("miles/v1/devices/term-43/responses/inbox", False),
        ("miles/v1/devices/term-42/responses/a/b", False),
        ("miles/v1/devices/term-42/responses/#", False),
        ("miles/v1/devices/term-42/responses/", False),
        ("miles/v1/devices/term-42/requests/system.ping", False),
        ("$SYS/broker/clients", False),
    ],
)
def test_response_topic_is_limited_to_the_device_own_inbox(
    response_topic: str, allowed: bool
) -> None:
    assert is_allowed_response_topic(DEVICE, response_topic) is allowed


def test_resolve_request_invalid_topic_returns_none() -> None:
    assert resolve_request("miles/v1/devices/x", b"", RESPONSE_TOPIC, None) is None


async def test_ping_replies_200_with_same_correlation_data_and_opaque_payload() -> None:
    response = await resolve_reply(_request(), BUILTIN_HANDLERS)

    assert response is not None
    assert response.topic == RESPONSE_TOPIC
    assert response.correlation_data == b"\x01\x02\x00\xfe"
    assert response.payload == b"\x00opaque\xff"
    assert response.status == HTTPStatus.OK


async def test_request_without_response_topic_is_not_processed() -> None:
    calls: list[Request] = []

    async def handler(request: Request) -> bytes:
        calls.append(request)
        return b""

    response = await resolve_reply(_request(response_topic=None), {"system.ping": handler})

    assert response is None
    assert calls == []


async def test_forbidden_response_topic_publishes_nothing_and_is_not_processed() -> None:
    calls: list[Request] = []

    async def handler(request: Request) -> bytes:
        calls.append(request)
        return b""

    forbidden = "miles/v1/devices/term-43/responses/inbox"
    response = await resolve_reply(_request(response_topic=forbidden), {"system.ping": handler})

    assert response is None
    assert calls == []


async def test_request_without_correlation_data_gets_none_back() -> None:
    response = await resolve_reply(_request(correlation_data=None), BUILTIN_HANDLERS)

    assert response is not None
    assert response.correlation_data is None


async def test_unknown_operation_replies_404() -> None:
    response = await resolve_reply(_request(operation="nope"), BUILTIN_HANDLERS)

    assert response is not None
    assert response.status == HTTPStatus.NOT_FOUND


async def test_handler_rejection_replies_its_4xx_status() -> None:
    async def illegible(request: Request) -> bytes:
        raise RequestRejectedError(HTTPStatus.BAD_REQUEST, "charge utile illisible")

    response = await resolve_reply(_request(operation="x"), {"x": illegible})

    assert response is not None
    assert (response.status, response.payload) == (HTTPStatus.BAD_REQUEST, b"")


async def test_handler_failure_replies_500_with_correlation_data() -> None:
    async def broken(request: Request) -> bytes:
        raise RuntimeError("panne interne, détail privé")

    response = await resolve_reply(_request(operation="x"), {"x": broken})

    assert response is not None
    assert response.status == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.correlation_data == b"\x01\x02\x00\xfe"
    assert b"priv" not in response.payload


async def test_concurrent_requests_keep_their_own_correlation_data() -> None:
    release = asyncio.Event()

    async def slow(request: Request) -> bytes:
        if request.payload == b"first":
            await release.wait()
        return request.payload

    handlers = {"x": slow}
    first = asyncio.create_task(
        resolve_reply(_request(operation="x", payload=b"first", correlation_data=b"A"), handlers)
    )
    second = await resolve_reply(
        _request(operation="x", payload=b"second", correlation_data=b"B"), handlers
    )
    release.set()
    first_response = await first

    assert second is not None and first_response is not None
    assert (second.correlation_data, second.payload) == (b"B", b"second")
    assert (first_response.correlation_data, first_response.payload) == (b"A", b"first")
