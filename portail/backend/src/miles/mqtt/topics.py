from __future__ import annotations

import re
from dataclasses import dataclass

# Convention de topics (version 1) :
#   demande : miles/v1/devices/<terminal>/requests/<opération>
#   réponse : miles/v1/devices/<terminal>/responses/<suffixe choisi par le terminal>
# Le broker n'autorise un terminal à publier que sous SON segment (motif %u de
# l'ACL Mosquitto) : le segment <terminal> d'une demande est donc fiable.
TOPIC_ROOT = "miles/v1/devices"
REQUESTS_SUBSCRIPTION = f"{TOPIC_ROOT}/+/requests/+"

_DEVICE = r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
_REQUEST_RE = re.compile(rf"^miles/v1/devices/({_DEVICE})/requests/([a-z][a-z0-9._-]{{0,63}})$")
# Un seul niveau, sans joker : le Response Topic vient du client et ne doit pas
# pouvoir désigner autre chose que la boîte de réponse du terminal lui-même.
_RESPONSE_SUFFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class RequestTopic:
    device: str
    operation: str


def parse_request_topic(topic: str) -> RequestTopic | None:
    match = _REQUEST_RE.match(topic)
    if match is None:
        return None
    return RequestTopic(device=match.group(1), operation=match.group(2))


def response_topic_prefix(device: str) -> str:
    return f"{TOPIC_ROOT}/{device}/responses/"


def is_allowed_response_topic(device: str, response_topic: str) -> bool:
    """Le terminal ne peut faire publier le back que dans sa propre boîte de réponse.

    C'est le topic où l'ACL du broker lui permet de souscrire : publier ailleurs
    ferait du back un relais vers un topic arbitraire choisi par le client.
    """
    prefix = response_topic_prefix(device)
    if not response_topic.startswith(prefix):
        return False
    return _RESPONSE_SUFFIX_RE.match(response_topic[len(prefix) :]) is not None
