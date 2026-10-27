from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from typing import Any

import aiomqtt
import pytest
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from pydantic import SecretStr

from miles.mqtt.protocol import BUILTIN_HANDLERS
from miles.mqtt.responder import MqttSettings, run_responder

pytestmark = pytest.mark.integration

INBOX = "miles/v1/devices/{device}/responses/inbox"
PING = "miles/v1/devices/{device}/requests/system.ping"
REPLY_TIMEOUT_S = 5.0
SILENCE_S = 1.5


def _env(name: str) -> str:
    # Posés par scripts/run-integration-tests.sh, qui lance un vrai Mosquitto avec
    # mosquitto/mosquitto.conf et mosquitto/acl du dépôt : c'est ce broker qu'on éprouve.
    value = os.environ.get(name)
    if not value:
        pytest.fail(f"{name} absent : lancer via scripts/run-integration-tests.sh")
    return value


def _device(name: str, identifier: str | None = None, **kwargs: Any) -> aiomqtt.Client:
    return aiomqtt.Client(
        _env("MILES_TEST_MQTT_HOST"),
        username=name,
        password=_env(f"MILES_TEST_MQTT_PASSWORD_{name.upper().replace('-', '_')}"),
        identifier=identifier or name,
        protocol=aiomqtt.ProtocolVersion.V5,
        **kwargs,
    )


def _request_properties(response_topic: str | None, correlation: bytes | None) -> Properties:
    properties = Properties(PacketTypes.PUBLISH)  # type: ignore[no-untyped-call]
    if response_topic is not None:
        properties.ResponseTopic = response_topic
    if correlation is not None:
        properties.CorrelationData = correlation
    return properties


@pytest.fixture
async def responder() -> AsyncIterator[None]:
    settings = MqttSettings(
        host=_env("MILES_TEST_MQTT_HOST"),
        port=1883,
        username="miles-backend",
        password=SecretStr(_env("MILES_TEST_MQTT_PASSWORD_MILES_BACKEND")),
        client_id="miles-backend-test",
    )
    task = asyncio.create_task(run_responder(settings, BUILTIN_HANDLERS))
    await asyncio.sleep(1.0)  # laisse le service souscrire avant les demandes
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _next_reply(client: aiomqtt.Client, wait_s: float) -> aiomqtt.Message | None:
    try:
        async with asyncio.timeout(wait_s):
            async for message in client.messages:
                return message
    except TimeoutError:
        return None
    return None


def _status(message: aiomqtt.Message) -> str:
    return dict(message.properties.UserProperty)["status"]  # type: ignore[union-attr]


async def test_ping_round_trip_copies_correlation_data_byte_for_byte(responder: None) -> None:
    correlation = bytes(range(256))
    async with _device("term-42") as device:
        await device.subscribe(INBOX.format(device="term-42"), qos=1)
        await device.publish(
            PING.format(device="term-42"),
            b"\x00payload\xff",
            qos=1,
            properties=_request_properties(INBOX.format(device="term-42"), correlation),
        )
        reply = await _next_reply(device, REPLY_TIMEOUT_S)

    assert reply is not None
    assert reply.payload == b"\x00payload\xff"
    assert reply.properties.CorrelationData == correlation  # type: ignore[union-attr]
    assert _status(reply) == "200"


async def test_unknown_operation_still_gets_an_answer(responder: None) -> None:
    async with _device("term-42") as device:
        await device.subscribe(INBOX.format(device="term-42"), qos=1)
        await device.publish(
            "miles/v1/devices/term-42/requests/nope",
            b"",
            qos=1,
            properties=_request_properties(INBOX.format(device="term-42"), b"c"),
        )
        reply = await _next_reply(device, REPLY_TIMEOUT_S)

    assert reply is not None and _status(reply) == "404"


async def test_reply_toward_another_device_inbox_is_never_published(responder: None) -> None:
    async with _device("term-42") as attacker, _device("term-43") as victim:
        await victim.subscribe(INBOX.format(device="term-43"), qos=1)
        await attacker.publish(
            PING.format(device="term-42"),
            b"spoof",
            qos=1,
            properties=_request_properties(INBOX.format(device="term-43"), b"c"),
        )
        leaked = await _next_reply(victim, SILENCE_S)

    assert leaked is None


async def test_broker_forbids_publishing_under_another_device_segment(responder: None) -> None:
    async with _device("term-42") as attacker, _device("term-43") as victim:
        await victim.subscribe(INBOX.format(device="term-43"), qos=1)
        # term-42 se fait passer pour term-43 : l'ACL du broker doit écarter la demande.
        await attacker.publish(
            PING.format(device="term-43"),
            b"spoof",
            qos=1,
            properties=_request_properties(INBOX.format(device="term-43"), b"c"),
        )
        leaked = await _next_reply(victim, SILENCE_S)

    assert leaked is None


async def test_request_without_response_topic_publishes_nothing(responder: None) -> None:
    async with _device("term-42") as device:
        await device.subscribe(INBOX.format(device="term-42"), qos=1)
        await device.publish(
            PING.format(device="term-42"), b"x", qos=1, properties=_request_properties(None, b"c")
        )
        reply = await _next_reply(device, SILENCE_S)

    assert reply is None


async def test_concurrent_requests_get_their_own_correlation_data(responder: None) -> None:
    async with _device("term-42") as device:
        await device.subscribe(INBOX.format(device="term-42"), qos=1)
        for index in range(10):
            await device.publish(
                PING.format(device="term-42"),
                f"p{index}".encode(),
                qos=1,
                properties=_request_properties(
                    INBOX.format(device="term-42"), f"c{index}".encode()
                ),
            )
        replies = [await _next_reply(device, REPLY_TIMEOUT_S) for _ in range(10)]

    pairs = {(r.properties.CorrelationData, r.payload) for r in replies if r is not None}  # type: ignore[union-attr]
    assert pairs == {(f"c{i}".encode(), f"p{i}".encode()) for i in range(10)}


async def test_disconnected_device_with_session_gets_reply_on_reconnect(responder: None) -> None:
    session = _session_properties()
    async with _device("term-42", clean_start=False, properties=session) as device:
        await device.subscribe(INBOX.format(device="term-42"), qos=1)
    # La session « term-42 » est hors ligne. Une seconde connexion du même terminal
    # (même compte, autre identifiant) envoie la demande : la réponse doit attendre
    # la session déconnectée, et non se perdre.
    async with _device("term-42", identifier="term-42-sender") as sender:
        await sender.publish(
            PING.format(device="term-42"),
            b"late",
            qos=1,
            properties=_request_properties(INBOX.format(device="term-42"), b"late"),
        )
    await asyncio.sleep(1.0)
    async with _device("term-42", clean_start=False, properties=session) as device:
        reply = await _next_reply(device, REPLY_TIMEOUT_S)

    assert reply is not None and reply.payload == b"late"


def _session_properties() -> Properties:
    properties = Properties(PacketTypes.CONNECT)  # type: ignore[no-untyped-call]
    properties.SessionExpiryInterval = 300
    return properties
