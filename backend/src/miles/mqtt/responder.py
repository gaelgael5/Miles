from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

import aiomqtt
import structlog
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties
from pydantic import SecretStr

from miles.mqtt.protocol import STATUS_PROPERTY, Handler, Response, resolve_reply, resolve_request
from miles.mqtt.topics import REQUESTS_SUBSCRIPTION

log = structlog.get_logger(__name__)

# QoS 1 dans les deux sens : un terminal déconnecté au moment de la réponse la
# reçoit à sa reconnexion s'il a une session persistante (Clean Start = 0,
# Session Expiry > 0) et une souscription QoS 1 ; sans session, elle est perdue.
QOS_AT_LEAST_ONCE = 1
RECONNECT_DELAY_S = 5.0


@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int
    username: str
    password: SecretStr
    client_id: str


def response_properties(response: Response) -> Properties:
    properties = Properties(PacketTypes.PUBLISH)  # type: ignore[no-untyped-call]  # paho non annoté
    # Recopiée octet pour octet, et jamais inventée : sans Correlation Data reçue,
    # la réponse n'en porte pas.
    if response.correlation_data is not None:
        properties.CorrelationData = response.correlation_data
    properties.UserProperty = [(STATUS_PROPERTY, str(response.status))]
    return properties


async def resolve_handle_message(
    client: aiomqtt.Client, message: aiomqtt.Message, handlers: Mapping[str, Handler]
) -> None:
    properties = message.properties
    request = resolve_request(
        message.topic.value,
        bytes(message.payload) if isinstance(message.payload, bytes | bytearray) else b"",
        getattr(properties, "ResponseTopic", None),
        getattr(properties, "CorrelationData", None),
    )
    if request is None:
        return
    response = await resolve_reply(request, handlers)
    if response is None:
        return
    await client.publish(
        response.topic,
        response.payload,
        qos=QOS_AT_LEAST_ONCE,
        properties=response_properties(response),
    )


async def run_responder(settings: MqttSettings, handlers: Mapping[str, Handler]) -> None:
    """Sert les demandes jusqu'à annulation, en se reconnectant après une coupure."""
    while True:
        try:
            await _serve(settings, handlers)
        except aiomqtt.MqttError as exc:
            log.warning("mqtt_connexion_perdue", reason=str(exc), retry_in_s=RECONNECT_DELAY_S)
            await asyncio.sleep(RECONNECT_DELAY_S)


async def _serve(settings: MqttSettings, handlers: Mapping[str, Handler]) -> None:
    async with aiomqtt.Client(
        settings.host,
        settings.port,
        username=settings.username,
        password=settings.password.get_secret_value(),
        identifier=settings.client_id,
        protocol=aiomqtt.ProtocolVersion.V5,
    ) as client:
        await client.subscribe(REQUESTS_SUBSCRIPTION, qos=QOS_AT_LEAST_ONCE)
        log.info("mqtt_pret", subscription=REQUESTS_SUBSCRIPTION)
        async with asyncio.TaskGroup() as tasks:
            async for message in client.messages:
                # Une tâche par demande : deux demandes concurrentes d'un même
                # terminal ne s'attendent pas, et chacune garde sa Correlation Data.
                tasks.create_task(resolve_handle_message(client, message, handlers))
