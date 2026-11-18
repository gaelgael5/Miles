"""Écrire un modèle dans une copie DÉJÀ ouverte : ce qui naît, et ce qui remplace.

Ces deux gestes ne touchent ni la base ni le journal : il leur suffit de la copie et de la
manière d'y committer. Ce sont eux qui portent les règles qui décident ce qui s'écrit — le
domaine qui doit exister, le nom déjà pris, le rejeu à l'identique qui n'écrit rien, la
version tenue par le système, et les renvois vérifiés avant la première écriture.

L'ORDRE compte et il est le même dans les deux : on refuse AVANT d'écrire quoi que ce soit,
parce qu'une copie à moitié écrite serait committée par le geste suivant.
"""

from __future__ import annotations

from miles_socle.events.model import EventAuthor

from miles.datamodels.errors import ModelNotFoundError
from miles.datamodels.layout import SHARED, ModelEntry, model_path
from miles.datamodels.links import check_references
from miles.datamodels.meta import meta_path, meta_text, read_version
from miles.datamodels.reading import described
from miles.datamodels.schema import ModelSchema, normalized, parse_schema
from miles.git.workcopy import WorkCopy
from miles.workshop.domains import domains_in
from miles.workshop.target import WorkBranches
from miles.workspaces.model import WorkspaceConflictError

_MESSAGE = "Modèle de données"


async def write_new(
    copy: WorkCopy,
    branches: WorkBranches,
    author: EventAuthor,
    entry: ModelEntry,
    content: str,
    schema: ModelSchema,
) -> tuple[ModelEntry, str | None]:
    """Écrit un modèle qui n'existe pas encore ; le même déjà là : rien n'est écrit, None."""
    # Le domaine se déclare à part (story 7fa00f56) : le créer ici au passage ferait
    # d'une faute de frappe un domaine de plus, sans que personne ne le voie.
    if entry.scope != SHARED and entry.scope not in domains_in(await copy.paths()):
        raise WorkspaceConflictError("domaine_inconnu")
    existing = await copy.read(entry.path)
    if existing is not None:
        if existing == content:
            return await described(copy, entry), None
        raise WorkspaceConflictError("nom_pris")
    await check_references(copy, entry, schema)
    await copy.write(entry.path, content)
    # Un modèle naît en version 1 : la version est au système, jamais au client.
    await copy.write(meta_path(entry.path), meta_text(1))
    commit = await branches.commit(copy, f"{_MESSAGE} {entry.path}", author)
    return await described(copy, entry), commit


async def write_replacement(
    copy: WorkCopy,
    branches: WorkBranches,
    author: EventAuthor,
    scope: str,
    name: str,
    content: str,
) -> tuple[ModelEntry, str | None]:
    """Le coeur d'un remplacement, dans une copie déjà ouverte ; None : rien à écrire."""
    schema = parse_schema(content)
    content = normalized(content, scope, name)
    entry = ModelEntry(scope, name, model_path(scope, name))
    existing = await copy.read(entry.path)
    if existing is None:
        raise ModelNotFoundError(entry.path)
    if existing == content:
        return await described(copy, entry), None
    await check_references(copy, entry, schema)
    version = read_version(await copy.read(meta_path(entry.path))) + 1
    await copy.write(entry.path, content)
    await copy.write(meta_path(entry.path), meta_text(version))
    commit = await branches.commit(copy, f"{_MESSAGE} {entry.path}", author)
    return await described(copy, entry), commit
