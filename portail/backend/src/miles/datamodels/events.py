"""Ce que le journal retient d'un geste sur un modèle, et l'écriture de ce fait.

Les formes, le nom tracé et l'écriture vivent ensemble parce qu'ils disent la même chose :
un fait de modèle, c'est un CHEMIN et un COMMIT, jamais un contenu. Les séparer aurait
laissé le bloc d'un côté et ce qui le remplit de l'autre, et c'est exactement là qu'un
champ s'ajoute d'un seul côté.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg
import structlog
from miles_socle.events.catalog import EventCatalog, EventShape, closed_block
from miles_socle.events.journal import db_write_event
from miles_socle.events.model import EventAuthor, NewEvent, ObjectRef

from miles.datamodels.layout import ModelEntry
from miles.event_shapes import GESTURE, NAME

log = structlog.get_logger(__name__)

CREATED_EVENT = "data_model.created"
DELETED_EVENT = "data_model.deleted"
REPLACED_EVENT = "data_model.replaced"
# Le CHEMIN du modèle dans le dépôt, et le geste : les trois faits portent le même bloc,
# parce que la question qu'on leur pose est la même — « quel modèle, et dans quel commit ? ».
_MODELE: dict[str, Any] = {"path": NAME, **GESTURE}
EVENT_SHAPES = (
    EventShape(CREATED_EVENT, "Modèle de données créé", closed_block(_MODELE)),
    EventShape(DELETED_EVENT, "Modèle de données supprimé", closed_block(_MODELE)),
    EventShape(REPLACED_EVENT, "Modèle de données remplacé", closed_block(_MODELE)),
)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)
# Le nom tracé de chaque fait. Une table et non trois appels dispersés : le fait et sa
# trace se lisent ensemble, et un fait de plus ne peut pas arriver sans sa ligne de journal.
_LOGGED = {
    CREATED_EVENT: "modele_de_donnees_cree",
    REPLACED_EVENT: "modele_de_donnees_remplace",
    DELETED_EVENT: "modele_de_donnees_supprime",
}


@dataclass(frozen=True)
class ModelJournal:
    """Où partent les faits de modèle : la base pour le journal, le log pour la trace."""

    pool: asyncpg.Pool
    catalog: EventCatalog
    now: Callable[[], datetime]

    async def db_write(
        self,
        workspace_id: str,
        event_type: str,
        author: EventAuthor,
        entry: ModelEntry,
        commit: str,
        branch: str,
    ) -> None:
        """Écrit le fait, puis le trace. À appeler APRÈS le push, jamais avant.

        Le journal dit ce qui est dans git : un fait écrit avant le push survivrait à un
        push qui échoue. Le contenu du modèle n'y va pas — le chemin et le commit
        suffisent à le retrouver, et le journal n'est pas un deuxième endroit où le
        paramétrage vivrait.
        """
        event = NewEvent(
            event_type,
            (ObjectRef("workspace", workspace_id),),
            author,
            {"path": entry.path, "commit": commit, "branch": branch},
        )
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)
        log.info(_LOGGED[event_type], workspace=workspace_id, path=entry.path)
