from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

from miles.mqtt.protocol import BUILTIN_HANDLERS, Response
from miles.mqtt.responder import resolve_handle_message, response_properties

DEVICE_TOPIC = "miles/v1/devices/term-42"


@dataclass
class _Topic:
    value: str


@dataclass
class _Message:
    topic: _Topic
    payload: Any
    properties: Any


class _FakeClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, Any, int, Any]] = []

    async def publish(self, topic: str, payload: Any, *, qos: int, properties: Any) -> None:
        self.published.append((topic, payload, qos, properties))


def _properties(**values: Any) -> Properties:
    properties = Properties(PacketTypes.PUBLISH)  # type: ignore[no-untyped-call]
    for name, value in values.items():
        setattr(properties, name, value)
    return properties


def test_response_properties_copy_correlation_data_and_carry_status() -> None:
    properties = response_properties(Response("t", b"", b"\x00\xff", 200))

    assert properties.CorrelationData == b"\x00\xff"
    assert properties.UserProperty == [("status", "200")]


def test_response_properties_without_correlation_data_invent_none() -> None:
    properties = response_properties(Response("t", b"", None, 500))

    assert not hasattr(properties, "CorrelationData")


async def test_handle_message_publishes_reply_qos1_on_response_topic() -> None:
    client = _FakeClient()
    message = _Message(
        _Topic(f"{DEVICE_TOPIC}/requests/system.ping"),
        b"ping",
        _properties(ResponseTopic=f"{DEVICE_TOPIC}/responses/inbox", CorrelationData=b"c1"),
    )

    await resolve_handle_message(client, message, BUILTIN_HANDLERS)  # type: ignore[arg-type]

    [(topic, payload, qos, properties)] = client.published
    assert (topic, payload, qos) == (f"{DEVICE_TOPIC}/responses/inbox", b"ping", 1)
    assert properties.CorrelationData == b"c1"


async def test_handle_message_without_response_topic_publishes_nothing() -> None:
    client = _FakeClient()
    message = _Message(_Topic(f"{DEVICE_TOPIC}/requests/system.ping"), b"ping", _properties())

    await resolve_handle_message(client, message, BUILTIN_HANDLERS)  # type: ignore[arg-type]

    assert client.published == []


async def test_handle_message_on_unknown_topic_publishes_nothing() -> None:
    client = _FakeClient()
    message = _Message(
        _Topic("autre/topic"), b"x", _properties(ResponseTopic=f"{DEVICE_TOPIC}/responses/i")
    )

    await resolve_handle_message(client, message, BUILTIN_HANDLERS)  # type: ignore[arg-type]

    assert client.published == []
