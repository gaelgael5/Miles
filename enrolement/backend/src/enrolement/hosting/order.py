"""Pousser l'ordre à l'environnement, et lire ce qu'il répond.

Le SEUL endroit, avec l'avis de révocation, où ce module compose un appel sortant. Les
règles n'y sont pas celles des routes qu'il sert : ce qui revient est la réponse d'un
autre service, bornée et validée avant toute relecture, et on ne déduit jamais d'elle plus
qu'elle ne dit. Les trois issues — appliqué, refusé, injoignable — ne se confondent jamais,
parce qu'elles n'appellent pas le même geste.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog
from miles_socle.signing.calls import post_signed
from miles_socle.signing.hosting import (
    HOSTED_VERSION_PATH,
    HOSTING_HTTP_TIMEOUT_S,
    HostedVersionIn,
    HostedVersionOut,
)
from miles_socle.signing.identity import ModuleIdentityService
from miles_socle.signing.identity_model import OriginMissingError
from pydantic import ValidationError

from enrolement.hosting.model import (
    COMMIT_RE,
    REFUSAL_NO_ORIGIN,
    REFUSAL_NOT_APPLIED,
    REFUSAL_REJECTED,
    REFUSAL_UNREACHABLE,
    REFUSAL_UNREADABLE,
    readable_refusal,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OrderOutcome:
    """Ce que l'ordre a produit : le commit que le pair SERT, ou ce qui a empêché.

    Jamais les deux, et jamais aucun des deux : c'est l'invariant que la base tient aussi
    (`hosted_version_reponse_coherente`). L'écran lit l'un ou l'autre, et porter les deux
    le laisserait choisir lequel croire.
    """

    served_commit: str | None
    refusal: str | None

    @property
    def applied(self) -> bool:
        return self.served_commit is not None


async def push_order(
    http: httpx.AsyncClient,
    module: ModuleIdentityService,
    *,
    origin: str | None,
    contact_url: str,
    workspace_id: str,
    number: int,
    commit: str,
) -> OrderOutcome:
    """Dit à l'environnement quelle version servir, et rend ce qu'il en a fait.

    Composé vers l'adresse de CONTACT, saisie par notre administrateur : l'origine
    déclarée d'une stack passe souvent par un intermédiaire qui ne nous laisse pas passer,
    et l'ordre n'arriverait jamais. Même raison que pour l'avis de révocation.

    Borné par `HOSTING_HTTP_TIMEOUT_S` et non par le client partagé : l'environnement va
    venir chercher le contenu du dépôt PENDANT que nous attendons sa réponse, et cinq
    secondes ne suffisent pas. La borne est au contrat pour que les deux bouts aient la
    même idée de ce qui est trop long.
    """
    if origin is None:
        # Sans adresse publique on ne sait pas signer, et un ordre non signé serait refusé
        # — à juste titre. Le dire plutôt que de l'émettre pour rien.
        log.warning("ordre_de_version_non_emis", contact_url=contact_url, reason="origine")
        return OrderOutcome(None, REFUSAL_NO_ORIGIN)
    corps = HostedVersionIn(
        workspace_id=workspace_id, number=number, commit=commit
    ).model_dump_json()
    try:
        reponse = await post_signed(
            http,
            await module.resolve_private_key(),
            origin=origin,
            contact_url=contact_url,
            path=HOSTED_VERSION_PATH,
            body=corps.encode("utf-8"),
            http_timeout_s=HOSTING_HTTP_TIMEOUT_S,
        )
    except (httpx.HTTPError, OriginMissingError) as panne:
        log.warning(
            "ordre_de_version_non_remis",
            contact_url=contact_url,
            reason=type(panne).__name__,
        )
        return OrderOutcome(None, REFUSAL_UNREACHABLE)
    return _lu(reponse, contact_url=contact_url, commit=commit)


def _lu(reponse: httpx.Response, *, contact_url: str, commit: str) -> OrderOutcome:
    """Ce que le pair a répondu, sans rien inventer de ce qu'il n'a pas dit."""
    if reponse.status_code == 401:
        # Il a répondu, et il nous refuse : distinct d'une panne de réseau. Le statut seul
        # ne dit pas pourquoi — son portillon d'authentification et son vérificateur de
        # signature rendent le même 401 —, et on ne choisit donc pas de cause.
        log.warning("ordre_de_version_refuse", contact_url=contact_url)
        return OrderOutcome(None, REFUSAL_REJECTED)
    if reponse.status_code != 200:
        log.warning(
            "ordre_de_version_reponse_inattendue",
            contact_url=contact_url,
            status_code=reponse.status_code,
        )
        return OrderOutcome(None, REFUSAL_UNREADABLE)
    try:
        accuse = HostedVersionOut.model_validate_json(reponse.content)
    except ValidationError:
        log.warning("ordre_de_version_accuse_illisible", contact_url=contact_url)
        return OrderOutcome(None, REFUSAL_UNREADABLE)
    if accuse.ordered_commit != commit:
        # Il accuse un AUTRE ordre que celui qu'on vient de pousser : deux administrateurs
        # ont choisi en même temps, ou la réponse ne vient pas de l'appel qu'on a émis.
        # L'écrire comme « servi » ferait afficher à jour une version qu'on n'a pas choisie.
        log.warning(
            "ordre_de_version_accuse_un_autre_ordre",
            contact_url=contact_url,
            acked_commit=accuse.ordered_commit,
        )
        return OrderOutcome(None, REFUSAL_UNREADABLE)
    if accuse.served_commit is None or not COMMIT_RE.match(accuse.served_commit):
        # Il a pris l'ordre sans l'appliquer — ou a répondu un commit qui n'en est pas un.
        # Sa raison est reprise si elle a la forme attendue, sinon « non appliqué », qui
        # est ce qu'on sait de sûr.
        return OrderOutcome(None, readable_refusal(accuse.reason) or REFUSAL_NOT_APPLIED)
    if accuse.served_commit != commit:
        # Il sert encore la version précédente : l'application n'est pas allée au bout, et
        # le dire ainsi vaut mieux que d'écrire un commit qui n'est pas celui demandé.
        return OrderOutcome(None, readable_refusal(accuse.reason) or REFUSAL_NOT_APPLIED)
    log.info("ordre_de_version_applique", contact_url=contact_url, commit=commit)
    return OrderOutcome(accuse.served_commit, None)
