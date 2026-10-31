from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import asyncpg
import structlog
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, EventTypeCatalog, NewEvent, ObjectRef

from miles.accounts.checks import delivery_problem
from miles.accounts.layout import (
    MODES,
    PATH,
    SERVED_MODES,
    AccountReference,
    Delivery,
    ReferenceProblem,
    read_reference,
    reference_text,
)
from miles.storages.layout import names_in as storage_names_in
from miles.storages.layout import read_storage, storage_path
from miles.workshop.reading import Read
from miles.workshop.target import Gesture, WorkBranches

log = structlog.get_logger(__name__)

SAVED_EVENT = "account_reference.saved"
REMOVED_EVENT = "account_reference.removed"
EVENT_TYPES = frozenset({SAVED_EVENT, REMOVED_EVENT})


class StorageUnknownError(Exception):
    """Stockage absent de la branche : on NOMME ceux qui existent (critère 3).

    Sans cette liste, l'écran ne peut que répéter ce que la personne a saisi, et un agent
    qui appelle la primitive MCP doit tâtonner.
    """

    def __init__(self, storage: str, known: list[str]) -> None:
        super().__init__(storage)
        self.storage = storage
        self.known = known


class DeliveryRefusedError(Exception):
    """L'envoi saisi ne tient pas : le mode, ou le champ d'adresse. On dit lequel.

    Distincte de `StorageUnknownError` : ce ne sont pas les mêmes listes à proposer, et
    un écran qui les confondrait renverrait vers la mauvaise correction.
    """

    def __init__(self, problem: ReferenceProblem) -> None:
        super().__init__(problem.code)
        self.problem = problem
        # Ce qu'il FALLAIT : sans ces listes, un agent refusé doit tâtonner.
        self.modes = list(MODES)
        self.served = list(SERVED_MODES)


@dataclass(frozen=True)
class ReferenceState:
    """Ce que la branche porte : rien, une référence saine, ou un fichier en défaut."""

    reference: AccountReference | None
    # Le modèle du stockage désigné, LU dans sa déclaration et jamais stocké ici. None
    # quand il n'y a pas de référence, ou que le stockage a disparu de la branche.
    model: str | None
    # Rempli quand le dépôt se contredit ; l'écran le montre au lieu de dire « aucune
    # référence », ce qui serait faux et effacerait silencieusement un réglage existant.
    problem: ReferenceProblem | None


EMPTY = ReferenceState(None, None, None)


@dataclass(frozen=True)
class Saved:
    state: ReferenceState
    # Vrai quand le fichier portait déjà exactement ce réglage : aucun commit n'a été
    # fait (critère 10). L'écran peut alors le dire sans mentir sur une modification.
    unchanged: bool


@dataclass(frozen=True)
class AccountsService:
    """La référence de compte d'une branche (story a3ece1e9).

    Déclarée dans git avec la branche, et non en base : elle désigne un storage, qui est
    un objet de la branche. En base, elle aurait nommé un objet qu'une autre branche n'a
    pas, ou a renommé, sans que rien ne le signale au moment du réglage (Gael, 31/10/2026).

    Le service DÉCLARE seulement : il n'interroge aucun compte et n'envoie aucun code.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventTypeCatalog
    now: Callable[[], datetime]

    async def resolve_get(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> ReferenceState:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            return await file_state(copy.read)

    async def resolve_save(
        self,
        author: EventAuthor,
        workspace_id: str,
        storage: str,
        delivery: Delivery | None = None,
        *,
        branch: str | None = None,
    ) -> Saved:
        """Désigne le stockage, et par quel mode et quel champ part le code.

        `delivery` omis EFFACE l'envoi : cet appel pose la référence entière, comme
        `save_chain` pose une chaîne entière. Fusionner avec l'existant ferait qu'aucun
        appel ne saurait retirer un envoi.
        """
        storage = storage.strip()
        wanted = AccountReference(storage, delivery)
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            known = storage_names_in(await copy.paths())
            if storage not in known:
                # Refusé AVANT d'écrire : un fichier qui désigne un storage absent est
                # exactement le défaut que le critère 8 fait signaler à la lecture. On
                # ne le crée pas soi-même.
                raise StorageUnknownError(storage, known)
            if delivery is not None:
                model = await _storage_model(copy.read, storage)
                if model is None:
                    raise StorageUnknownError(storage, known)
                problem = await delivery_problem(copy.read, model, delivery, "envoi")
                if problem is not None:
                    raise DeliveryRefusedError(problem)
            current = await copy.read(PATH)
            if current is not None and read_reference(current) == wanted:
                return Saved(await file_state(copy.read), True)
            await copy.write(PATH, reference_text(wanted))
            commit = await self.branches.commit(copy, f"Référence de compte {storage}", author)
            state = await file_state(copy.read)
        await self._journal(SAVED_EVENT, workspace_id, author, commit, copy.branch, storage)
        log.info(
            "reference_compte_enregistree",
            workspace=workspace_id,
            storage=storage,
            mode=None if delivery is None else delivery.mode,
        )
        return Saved(state, False)

    async def resolve_remove(
        self, author: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> bool:
        """Retire la référence. Rend False si la branche n'en portait aucune.

        Pas une erreur dans ce cas : le geste demande que la branche n'ait plus de
        référence, et c'est déjà vrai. Rendre une erreur ferait échouer un rejeu.
        """
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            if await copy.read(PATH) is None:
                return False
            await copy.remove(PATH)
            commit = await self.branches.commit(copy, "Retrait de la référence de compte", author)
        await self._journal(REMOVED_EVENT, workspace_id, author, commit, copy.branch, None)
        log.info("reference_compte_retiree", workspace=workspace_id)
        return True

    async def _journal(
        self,
        kind: str,
        workspace_id: str,
        author: EventAuthor,
        commit: str,
        branch: str,
        storage: str | None,
    ) -> None:
        properties: dict[str, object] = {"commit": commit, "branch": branch}
        if storage is not None:
            properties["storage"] = storage
        event = NewEvent(kind, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


async def file_state(read: Read) -> ReferenceState:
    """Lit le fichier ET ce qu'il désigne : un réglage ne vaut que si sa cible existe.

    Prend un `read` et non une copie de travail : c'est tout ce dont cette lecture a
    besoin, et c'est ce qui la rend mesurable sans base ni forge — les quatre états
    qu'elle distingue sont la partie où une erreur se verrait le plus tard.
    """
    text = await read(PATH)
    if text is None:
        return EMPTY
    doc = read_reference(text)
    if doc is None:
        return ReferenceState(None, None, ReferenceProblem(PATH, "fichier_illisible"))
    declaration = await read(storage_path(doc.storage))
    if declaration is None:
        # Le storage a disparu de la branche depuis le réglage (critère 9), ou le fichier
        # a été écrit à la main sur un nom qui n'existe pas (critère 8). Même défaut, même
        # message : le réglage est RENDU, avec ce qui cloche, et jamais réécrit en silence.
        return ReferenceState(doc, None, ReferenceProblem(PATH, "storage_inconnu", doc.storage))
    storage = read_storage(declaration)
    if storage is None:
        return ReferenceState(doc, None, ReferenceProblem(PATH, "storage_illisible", doc.storage))
    if doc.delivery is not None:
        # Le champ d'adresse est revérifié À LA LECTURE, et pas seulement à l'écriture :
        # le modèle du storage vit dans la branche et peut perdre la propriété désignée
        # après coup. Sans ce contrôle, l'écran montrerait un réglage qui a l'air bon.
        problem = await delivery_problem(read, storage.model, doc.delivery, PATH)
        if problem is not None:
            return ReferenceState(doc, storage.model, problem)
    return ReferenceState(doc, storage.model, None)


async def _storage_model(read: Read, name: str) -> str | None:
    declaration = await read(storage_path(name))
    doc = None if declaration is None else read_storage(declaration)
    return None if doc is None else doc.model
