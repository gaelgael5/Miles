from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus

import structlog

from miles.mqtt.topics import is_allowed_response_topic, parse_request_topic

log = structlog.get_logger(__name__)

# Le statut voyage dans une User Property, pas dans la charge utile : le socle
# route et qualifie la réponse sans décoder un contenu qui lui reste opaque.
STATUS_PROPERTY = "status"


@dataclass(frozen=True)
class Request:
    device: str
    operation: str
    payload: bytes
    response_topic: str | None
    correlation_data: bytes | None


@dataclass(frozen=True)
class Response:
    topic: str
    payload: bytes
    correlation_data: bytes | None
    status: int


class RequestRejectedError(Exception):
    """Levée par une opération qui refuse la demande (4xx), par exemple illisible."""

    def __init__(self, status: HTTPStatus, reason: str) -> None:
        super().__init__(reason)
        self.status = status


Handler = Callable[[Request], Awaitable[bytes]]


async def ping(request: Request) -> bytes:
    """Opération de diagnostic : renvoie la charge utile telle quelle."""
    return request.payload


BUILTIN_HANDLERS: Mapping[str, Handler] = {"system.ping": ping}


def resolve_request(
    topic: str, payload: bytes, response_topic: str | None, correlation_data: bytes | None
) -> Request | None:
    parsed = parse_request_topic(topic)
    if parsed is None:
        log.warning("mqtt_demande_topic_invalide")
        return None
    return Request(parsed.device, parsed.operation, payload, response_topic, correlation_data)


async def resolve_reply(request: Request, handlers: Mapping[str, Handler]) -> Response | None:
    """Traite une demande et rend la réponse à publier, ou None s'il ne faut rien publier.

    Toute demande reçoit une réponse avec son statut (protocole posé le 19/10/2026),
    sauf quand il n'existe aucun topic où répondre sans fuite.
    """
    context = {"device": request.device, "operation": request.operation}
    if request.response_topic is None:
        # Pas de topic de réponse : la demande viole le protocole. Répondre exigerait
        # de deviner un topic, ce qui serait une fuite ; on ne traite pas.
        log.warning("mqtt_demande_refusee_sans_response_topic", **context)
        return None
    if not is_allowed_response_topic(request.device, request.response_topic):
        log.warning("mqtt_response_topic_interdit", **context)
        return None
    status, body = await _resolve_status_and_body(request, handlers, context)
    return Response(request.response_topic, body, request.correlation_data, status)


async def _resolve_status_and_body(
    request: Request, handlers: Mapping[str, Handler], context: dict[str, str]
) -> tuple[int, bytes]:
    handler = handlers.get(request.operation)
    if handler is None:
        log.warning("mqtt_operation_inconnue", **context)
        return HTTPStatus.NOT_FOUND, b""
    try:
        return HTTPStatus.OK, await handler(request)
    except RequestRejectedError as exc:
        log.warning("mqtt_demande_rejetee", status=int(exc.status), reason=str(exc), **context)
        return exc.status, b""
    except Exception:
        # Un scénario attend : un silence le bloquerait jusqu'à son propre délai.
        # On répond 500, et la cause va au journal, pas au terminal.
        log.exception("mqtt_traitement_en_echec", **context)
        return HTTPStatus.INTERNAL_SERVER_ERROR, b""
