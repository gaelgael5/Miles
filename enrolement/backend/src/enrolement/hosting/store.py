"""Les requêtes de la version hébergée, et la source git du workspace qu'elle vise.

Comme ailleurs dans ce module, les listes de colonnes sont écrites LITTÉRALEMENT dans
chaque requête : les factoriser rendrait illisible ce que chacune touche, et c'est
justement ce qu'on vient vérifier quand une ligne est fausse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from enrolement.hosting.model import HostedVersion


class HostingDb(Protocol):
    async def execute(self, query: str, *args: Any) -> str: ...
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


@dataclass(frozen=True)
class GitSource:
    """Où lire git pour un workspace : la connexion confiée qui l'expose, et son dépôt.

    Les trois ensemble parce que lire git en demande trois : le dépôt, le credential — que
    seule la paire (pair, connexion) permet d'ouvrir — et rien d'autre. Les séparer ferait
    tenir la jointure à l'appelant, qui n'a aucune raison de connaître ce schéma.
    """

    peer_base_url: str
    connection_id: str
    repo_url: str | None


@dataclass(frozen=True)
class OrderedForPeer:
    """Ce qu'un pair a le droit de demander : SON workspace, au commit qu'on lui a ordonné."""

    environment_id: UUID
    workspace_id: str
    commit: str


def _hosted(row: Any) -> HostedVersion:
    return HostedVersion(
        int(row["number"]),
        row["commit_sha"],
        row["ordered_at"],
        row["served_commit"],
        row["refusal"],
        row["acked_at"],
    )


async def db_get_hosted_version(db: HostingDb, environment_id: UUID) -> HostedVersion | None:
    row = await db.fetchrow(
        "SELECT number, commit_sha, ordered_at, served_commit, refusal, acked_at"
        " FROM hosted_version WHERE environment_id = $1",
        environment_id,
    )
    return None if row is None else _hosted(row)


async def db_list_hosted_versions(db: HostingDb, /) -> dict[UUID, HostedVersion]:
    """Toutes les versions ordonnées, par environnement : l'écran en liste plusieurs.

    Une requête et non une par ligne : la liste des environnements est affichée en entier,
    et interroger par environnement y ferait autant d'allers-retours que d'entrées.
    """
    rows = await db.fetch(
        "SELECT environment_id, number, commit_sha, ordered_at, served_commit, refusal,"
        " acked_at FROM hosted_version"
    )
    return {row["environment_id"]: _hosted(row) for row in rows}


async def db_order_version(
    db: HostingDb, environment_id: UUID, number: int, commit: str, now: datetime
) -> None:
    """Enregistre l'ordre, et EFFACE la réponse précédente.

    L'effacement n'est pas un détail : garder l'ancien `served_commit` ferait lire « à
    jour » sur une ligne dont l'ordre vient de changer, puisque la comparaison porte sur
    le commit ordonné. La réponse appartient à l'ordre qui l'a provoquée.
    """
    await db.execute(
        "INSERT INTO hosted_version (environment_id, number, commit_sha, ordered_at,"
        " served_commit, refusal, acked_at) VALUES ($1, $2, $3, $4, NULL, NULL, NULL)"
        " ON CONFLICT (environment_id) DO UPDATE SET number = excluded.number,"
        " commit_sha = excluded.commit_sha, ordered_at = excluded.ordered_at,"
        " served_commit = NULL, refusal = NULL, acked_at = NULL",
        environment_id,
        number,
        commit,
        now,
    )


async def db_record_ack(
    db: HostingDb,
    environment_id: UUID,
    served_commit: str | None,
    refusal: str | None,
    now: datetime,
) -> None:
    """Écrit ce que le pair a répondu. L'un ou l'autre, jamais les deux — la base le tient."""
    await db.execute(
        "UPDATE hosted_version SET served_commit = $2, refusal = $3, acked_at = $4"
        " WHERE environment_id = $1",
        environment_id,
        served_commit,
        refusal,
        now,
    )


async def db_delete_hosted_version(db: HostingDb, environment_id: UUID) -> bool:
    """Retire la version ordonnée, et dit si une ligne est partie.

    Le booléen décide si l'event de libération s'écrit : sans lui, changer le workspace
    d'un environnement qui n'avait aucune version journaliserait une libération qui n'a
    pas eu lieu.
    """
    deleted = await db.execute(
        "DELETE FROM hosted_version WHERE environment_id = $1", environment_id
    )
    return deleted != "DELETE 0"


async def db_git_source(db: HostingDb, workspace_id: str) -> GitSource | None:
    """La connexion confiée qui expose ce workspace, et le dépôt qu'il travaille.

    Restreinte au pair de PARAMÉTRAGE par la jointure, et non seulement par la table : un
    jour où deux espèces confieraient des connexions, lire sans cette condition rendrait
    la ligne de n'importe laquelle. Rend nul quand personne ne l'expose — le cas d'un
    paramétrage révoqué dont le placement a survécu.
    """
    row = await db.fetchrow(
        "SELECT w.peer_base_url, w.connection_id, w.repo_url FROM confided_git_workspace w"
        " JOIN environment_peer p ON p.base_url = w.peer_base_url AND p.species = 'parametrage'"
        " WHERE w.id = $1",
        workspace_id,
    )
    if row is None:
        return None
    return GitSource(row["peer_base_url"], row["connection_id"], row["repo_url"])


async def db_ordered_for_peer(db: HostingDb, peer_base_url: str) -> OrderedForPeer | None:
    """Ce qui est ordonné à l'environnement apparié sous cette origine.

    C'est la garde de la route du relais, et elle est écrite en SQL plutôt qu'en trois
    lectures : l'appariement, l'environnement qu'il sert, le workspace qui y est placé et
    la version qui lui est ordonnée doivent se correspondre TOUS, et une jointure ne peut
    pas en oublier un. Nul veut dire « rien ne lui est ordonné », donc rien à servir.
    """
    row = await db.fetchrow(
        "SELECT e.id, e.workspace_id, h.commit_sha FROM environment_peer p"
        " JOIN environment e ON e.id = p.environment_id"
        " JOIN hosted_version h ON h.environment_id = e.id"
        " WHERE p.base_url = $1 AND p.species = 'environnement' AND e.workspace_id IS NOT NULL",
        peer_base_url,
    )
    if row is None:
        return None
    return OrderedForPeer(row["id"], row["workspace_id"], row["commit_sha"])
