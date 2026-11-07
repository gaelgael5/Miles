"""Essayer une méthode d'ingestion depuis l'écran : le back-office frappe sa PROPRE route.

Décision de Gael du 04/11/2026 : « la back-office se débrouille seul pour avoir une clef
en interne qui permette de consommer le service en interne parce que l'utilisateur s'est
déjà authentifié. »

**Par la route, et non par le service.** Appeler `IngestionService` directement serait plus
court et sauterait exactement ce qu'on veut éprouver : la présentation de l'en-tête, la
vérification de l'empreinte, la relecture des octrois contre la version servie, et les
codes de refus que l'appelant tiers verra. Un essai qui ne passe pas par la porte ne dit
rien de la porte.

**Par l'application elle-même, et non par le réseau.** Le transport ASGI rejoue la chaîne
entière — portillon, routage, gestionnaire — sans que le service ait à connaître son propre
port ni à dépendre de la boucle locale. Ce que l'on saute est la prise réseau, qui n'est
pas ce qu'on essaie.

**Aucun garde-fou** (même décision) : l'essai transforme, écrit, fait avancer la date de
dernière vue et produit ses events, comme n'importe quel dépôt de partenaire. La trace est
le journal des appels.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import structlog
from fastapi import FastAPI
from miles_socle.apikeys.presentation import API_KEY_HEADER
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from environnement.apikeys.self_key import SelfKeyService
from environnement.ingestion.api_ingest import INGEST_PATH
from environnement.ingestion.model import CONTENT_TYPE, INGESTION_OBJECT_KIND

log = structlog.get_logger(__name__)

# Qui a lancé un essai. Le journal des appels attribue un dépôt à une CLÉ, jamais à une
# personne — c'est voulu —, donc sans cet event un essai serait indiscernable du dépôt
# d'un partenaire dans l'historique.
TRIAL_EVENT = "environment.ingestion_trial"
EVENT_TYPES = frozenset({TRIAL_EVENT})

# L'hôte que porte l'appel interne. Il ne sert qu'à l'en-tête `Host` : le point d'entrée
# ne le lit pas, et aucune résolution de nom n'a lieu — le transport est l'application.
TRIAL_ORIGIN = "http://environnement.interne"


@dataclass(frozen=True)
class TrialOutcome:
    """Ce que le point d'entrée a répondu, rendu TEL QUEL à l'écran.

    Le corps n'est pas reformulé : l'intérêt de l'essai est de montrer ce qu'un partenaire
    recevra, et une réponse réécrite par l'écran n'est plus celle du contrat.
    """

    status: int
    body: Any


@dataclass(frozen=True)
class IngestionTrial:
    pool: asyncpg.Pool
    self_keys: SelfKeyService
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_trial(
        self,
        app: FastAPI,
        author: EventAuthor,
        *,
        source: str,
        mode: str,
        body: bytes | AsyncIterator[bytes],
        length: int | None = None,
    ) -> TrialOutcome:
        """Dépose `body` sur l'entrée désignée, avec la clé du back-office.

        `app` est passée par la route : c'est elle qui tient l'application, et la garder
        ici ferait une référence circulaire entre le câblage et ce service.

        **`body` peut être un FLUX** depuis le 07/11/2026 (story `1a3fc5a7`) : en mode
        fichier, la route donne l'itérateur de la requête au lieu de son corps lu, et le
        document traverse sans que rien ne le garde. Vérifié dans le httpx installé
        (`_transports/asgi.py`) : le transport itère `request.stream` et émet un message
        `http.request` par tronçon avec `more_body`, donc le `request.stream()` du point
        d'entrée reçoit bien les tronçons un par un — ce n'est pas une mise en tampon
        déguisée. Aucun délai n'est en jeu : ce transport ne lit pas celui du client.

        `length` est la taille que l'appelant a annoncée, quand il l'a annoncée.
        """
        cle = await self.self_keys.resolve_usable(author)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=TRIAL_ORIGIN) as client:
            # La valeur de la clé ne se déballe qu'ICI, au point d'injection, et ne part
            # dans aucun journal : seule l'en-tête la porte, le temps de l'appel.
            recu = await client.post(
                INGEST_PATH.format(source=source, mode=mode),
                content=body,
                headers=_headers(cle.reveal(), length),
            )
        rendu = TrialOutcome(status=recu.status_code, body=_body(recu))
        log.info(
            "essai_d_ingestion",
            source=source,
            mode=mode,
            status=rendu.status,
            subject=author.subject,
        )
        await self._journalise(author, source, mode, rendu)
        return rendu

    async def _journalise(
        self, author: EventAuthor, source: str, mode: str, rendu: TrialOutcome
    ) -> None:
        """Inscrit QUI a lancé l'essai, rattaché au dépôt que la réponse nomme.

        **Après le dépôt, et donc dans une autre transaction que lui** — c'est un écart
        assumé à la règle « aucun fait observable sans sa trace dans la même
        transaction », et il n'a pas d'autre issue : l'identifiant du dépôt n'existe qu'une
        fois la réponse rendue. Un arrêt entre les deux laisse un dépôt sans son auteur
        humain ; on préfère ce trou, visible et rare, à l'alternative — faire confiance à
        une en-tête d'identité sur une route publique, que n'importe quel tiers forgerait.
        """
        ingestion = _ingestion_id(rendu.body)
        if ingestion is None:
            # Un refus n'a rien créé : il n'y a aucun dépôt à rattacher, et le journal
            # d'appels n'en porte pas non plus. La tentative reste dans les journaux.
            return
        event = NewEvent(
            TRIAL_EVENT,
            (ObjectRef(INGESTION_OBJECT_KIND, ingestion),),
            author,
            {"source": source, "mode": mode, "status": rendu.status},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


def _body(recu: httpx.Response) -> Any:
    """Le corps de la réponse, en JSON quand c'en est, en texte sinon.

    En texte sinon plutôt que de lever : une réponse inattendue — une page d'erreur du
    cadre, par exemple — doit arriver jusqu'à l'écran pour être diagnostiquée, pas
    disparaître dans une exception d'analyse syntaxique.
    """
    try:
        return json.loads(recu.content)
    except ValueError:
        return {"detail": recu.text[:2000]}


def _ingestion_id(body: Any) -> str | None:
    identifiant = body.get("id") if isinstance(body, dict) else None
    return identifiant if isinstance(identifiant, str) else None


def _headers(cle: str, length: int | None) -> dict[str, str]:
    """Les en-têtes de l'appel interne, la taille annoncée COMPRISE quand on la connaît.

    Relayer `Content-Length` n'est pas cosmétique : sans lui, httpx annonce
    `Transfer-Encoding: chunked` pour un corps en flux, le point d'entrée ne connaît plus
    la taille promise, et ses deux refus bon marché — `fichier_trop_grand` et
    `quota_de_disque_atteint` sur la taille ANNONCÉE — ne peuvent plus tomber avant la
    lecture. Un document de dix gigaoctets serait alors écrit sur le disque jusqu'à ce que
    la garde sur la taille mesurée l'arrête, au lieu d'être refusé au premier octet.

    Que l'en-tête explicite l'emporte est vérifié dans le httpx installé et non supposé :
    `Request._prepare` saute son `Transfer-Encoding` automatique quand `Content-Length` est
    déjà là (`_models.py`). Si cette précédence changeait, le dépôt resterait correct — la
    garde sur la taille mesurée tient — mais le refus cesserait d'être immédiat.
    """
    entetes = {API_KEY_HEADER: cle, "Content-Type": CONTENT_TYPE}
    if length is not None:
        entetes["Content-Length"] = str(length)
    return entetes
