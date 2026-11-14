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
from miles_socle.git.versions import SavedVersion

from miles.datamodels.layout import SHARED, model_path
from miles.datamodels.schema import normalized, parse_schema
from miles.event_shapes import BRANCH, COMMIT
from miles.git.holdspace import HeldCopy
from miles.git.versions import VersionTakenError, fetch_versions, restore_tree, same_tree, tag_head
from miles.git.workcopy import WorkCopy
from miles.workflowevents.dsl import EventType, fragment_path, render, writable
from miles.workflowevents.dsl import parse as parse_fragment
from miles.workshop.conversion import A_JOUR, MELANGEE, Layout, layout_of
from miles.workshop.target import Gesture, WorkBranches
from miles.workshop.validation import FileReport, validate_branch
from miles.workspaces.model import WorkspaceConflictError, WorkspaceInputError, commit_author

log = structlog.get_logger(__name__)

SAVED_EVENT = "work_version.saved"
RESTORED_EVENT = "work_version.restored"
CONVERTED_EVENT = "work_layout.converted"
# Ce qu'une version enregistrée EST : son numéro, le commit qu'elle étiquette, le libellé
# saisi, et la branche d'où elle a été prise. Le libellé peut être vide — c'est une saisie.
_VERSION: dict[str, object] = {
    "version": {"type": "integer", "minimum": 1},
    "commit": COMMIT,
    "label": {"type": "string"},
    "branch": BRANCH,
}
EVENT_SHAPES = (
    EventShape(SAVED_EVENT, "Version de travail enregistrée", closed_block(_VERSION)),
    EventShape(
        RESTORED_EVENT,
        "Version de travail restaurée",
        # DEUX commits, et c'est tout l'intérêt : celui de la version restaurée, et celui
        # du commit de retour qui vient d'être écrit. Un seul des deux ne dirait pas ce
        # qu'il faut annuler pour défaire la restauration.
        closed_block({**_VERSION, "restored_commit": COMMIT}),
    ),
    EventShape(
        CONVERTED_EVENT,
        "Disposition du dépôt convertie",
        # Le NOMBRE de fichiers déplacés, pas leur liste : une conversion en déplace
        # autant qu'il y a de modèles, et le commit porte déjà le détail. Ce que cet
        # event sert à retrouver, c'est QUAND une branche est passée à la nouvelle
        # disposition, et par quel commit on l'annule.
        closed_block(
            {"branch": BRANCH, "commit": COMMIT, "moved": {"type": "integer", "minimum": 1}}
        ),
    ),
)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)
LABEL_MAX = 200


class InvalidConfigurationError(Exception):
    """Le paramétrage ne passe pas les règles : on ne fige pas un état incohérent."""

    def __init__(self, reports: list[FileReport]) -> None:
        super().__init__(f"{len(reports)} fichier(s) en défaut")
        self.reports = reports


class VersionNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class FreezeBlock:
    """Ce qui empêche d'enregistrer une version ici, et le DÉTAIL quand c'est le paramétrage.

    Les rapports sont rendus AVEC la raison, et pas à sa place : « publiez d'abord » et
    « ces trois fichiers ne passent pas les règles » sont deux choses, et celui qui
    publiera veut savoir tout de suite que le figement échouera ensuite. C'est la demande
    de Gael du 01/11/2026 — « il faudrait que le message d'erreur arrive avant que j'aie
    envie de commiter ».
    """

    reason: str | None
    reports: tuple[FileReport, ...] = ()


@dataclass(frozen=True)
class WorkshopService:
    """Enregistrement explicite d'une version sur la branche de travail (story 94b06105).

    Jamais automatique : la cohérence de l'état figé vient de l'intention de quelqu'un,
    pas de la mécanique. Aucun merge vers une branche d'environnement : reporté par Gael.
    """

    pool: asyncpg.Pool
    branches: WorkBranches
    catalog: EventCatalog
    now: Callable[[], datetime]

    async def resolve_list(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> list[SavedVersion]:
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            mine, _ = await self._branch_versions(workspace_id, copy)
            return mine

    async def resolve_freezable(
        self, viewer: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> FreezeBlock:
        """Ce qui empêche d'enregistrer une version, et pourquoi, SANS avoir à l'essayer.

        Demandé par Gael le 25/10/2026 : l'écran grisait le bouton sur les seuls droits,
        et laissait cliquer ce que le serveur allait refuser. Les raisons de refus sont
        celles de `resolve_save`, lues ici par le MÊME code — une règle recopiée dans
        l'écran dériverait de celle qui refuse vraiment.

        **Le paramétrage est VALIDÉ ici depuis le 01/11/2026** (Gael : « il faudrait que
        le message d'erreur arrive avant que j'aie envie de commiter »). Jusque-là, la
        validation n'avait lieu qu'à l'enregistrement : on apprenait qu'un fichier ne
        passait pas les règles après avoir voulu figer, parfois après avoir publié pour
        rien. Elle lit la copie DÉJÀ sur disque — le coût cher, le `checkout`, est payé
        de toute façon par cette route.

        L'ordre des raisons est celui de `resolve_save`, et c'est volontaire : la raison
        rendue est celle que l'enregistrement opposerait VRAIMENT. Les rapports, eux,
        partent dans tous les cas — celui qui doit d'abord publier a le droit de savoir
        que le figement échouera ensuite.
        """
        async with self.branches.checkout(
            workspace_id, branch, by=viewer, gesture=Gesture.READ
        ) as copy:
            reports = tuple(await validate_branch(copy))
            if isinstance(copy, HeldCopy) and await copy.unpublished():
                return FreezeBlock("publication_requise", reports)
            mine, _ = await self._branch_versions(workspace_id, copy)
            last = mine[0] if mine else None
            if last is not None and await same_tree(copy, last.commit):
                return FreezeBlock("rien_a_figer", reports)
        return FreezeBlock("parametrage_invalide" if reports else None, reports)

    async def resolve_save(
        self, author: EventAuthor, workspace_id: str, label: str, *, branch: str | None = None
    ) -> tuple[SavedVersion, bool]:
        """Fige la tête de la branche ; rend (version, déjà_là). Rejeu : sans effet."""
        label = _label(label)
        # Pas une modification : une étiquette fige la branche sans en changer le contenu,
        # et reste permise sur la racine (Gael, 22/10/2026). Sur une branche fille, elle
        # suppose la main et une tête publiée (9def0adc, critère 11).
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.FREEZE
        ) as copy:
            mine, last_number = await self._branch_versions(workspace_id, copy)
            last = mine[0] if mine else None
            if last is not None and await same_tree(copy, last.commit):
                if last.commit == copy.head and last.label == label:
                    return last, True
                raise WorkspaceConflictError("rien_a_figer")
            # Sur une branche tenue, l'étiqueteur est la personne telle que la forge la
            # connaît, comme l'auteur de ses commits ; sur la racine, l'auteur de Miles.
            identity = copy.signature if isinstance(copy, HeldCopy) else commit_author(author)
            reports = await validate_branch(copy)
            if reports:
                raise InvalidConfigurationError(reports)
            # Numéro unique au dépôt (Gael, 22/10/2026) : un numéro désigne un seul état,
            # quelle que soit la branche, et c'est lui qu'on déploiera.
            number = last_number + 1
            try:
                # La version fige la tête lue au départ, et la réponse dit laquelle : une
                # écriture arrivée entre-temps n'y entre pas (critère 6).
                await tag_head(copy, number, label, identity)
            except VersionTakenError:
                raise WorkspaceConflictError("version_concurrente") from None
            saved = SavedVersion(number, label, copy.head, identity, self.now(), copy.branch)
        await self._event(workspace_id, SAVED_EVENT, author, _summary(saved, copy.branch))
        log.info("version_enregistree", workspace=workspace_id, version=number)
        return saved, False

    async def resolve_restore(
        self, author: EventAuthor, workspace_id: str, number: int, *, branch: str | None = None
    ) -> str:
        """Revient à une version par un NOUVEAU commit : l'historique n'est pas réécrit."""
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.EDIT
        ) as copy:
            # Seulement les versions de cette branche : ses modifications lui sont propres,
            # y ramener l'état d'une autre branche serait une fusion déguisée.
            mine, _ = await self._branch_versions(workspace_id, copy)
            versions = {v.number: v for v in mine}
            version = versions.get(number)
            if version is None:
                raise VersionNotFoundError(number)
            if await same_tree(copy, version.commit):
                raise WorkspaceConflictError("deja_a_cette_version")
            await restore_tree(copy, version.commit)
            message = f"Retour à la version {number} — {version.label}"
            commit = await self.branches.commit(copy, message, author)
        properties = _summary(version, copy.branch) | {"restored_commit": commit}
        await self._event(workspace_id, RESTORED_EVENT, author, properties)
        log.info("version_restauree", workspace=workspace_id, version=number)
        return commit

    async def _branch_versions(
        self, workspace_id: str, copy: WorkCopy
    ) -> tuple[list[SavedVersion], int]:
        """Versions de la branche de la copie, et le dernier numéro pris dans tout le dépôt."""
        every = await fetch_versions(copy)
        base = (await self.branches.base_workspace(workspace_id)).work_branch
        # Une étiquette sans branche date d'avant les branches filles : elle est à la base.
        mine = [v for v in every if (v.branch or base) == copy.branch]
        return mine, every[0].number if every else 0

    async def resolve_convert_layout(
        self, author: EventAuthor, workspace_id: str, *, branch: str | None = None
    ) -> int:
        """Déplace les modèles des anciens dossiers vers `models/`, en UN commit relisible.

        Le seul geste qui passe la garde de disposition — voir `miles.workshop.conversion`
        pour la raison de ne rien convertir tout seul. Rejoué sur une branche déjà à jour :
        sans effet et sans commit vide, parce qu'un commit sans changement se lirait comme
        une seconde conversion.

        Un ex-event ne fait pas que changer de dossier : son `$id` est réécrit — il portait
        `miles:/events/…`, qu'aucun storage ne résout — et il est DÉCLARÉ dans l'artefact
        de son périmètre. Sans cette déclaration, la conversion perdrait l'information qui
        distinguait un event d'un modèle, et personne ne saurait la retrouver.
        """
        async with self.branches.checkout(
            workspace_id, branch, by=author, gesture=Gesture.MIGRATE
        ) as copy:
            layout = layout_of(await copy.paths())
            if layout.kind == MELANGEE:
                # On ne devine pas lequel des deux dossiers fait foi : le dire, et laisser
                # un humain trancher dans la forge.
                raise WorkspaceConflictError("disposition_melangee")
            if layout.kind == A_JOUR:
                return 0
            if layout.conflicts:
                # Un ex-event dont le nom est déjà pris par un modèle du même périmètre :
                # on n'écrase pas, on le dit. Les deux documents sont dans la forge, et
                # c'est là qu'un humain choisit lequel garder.
                raise WorkspaceConflictError("noms_en_conflit")
            illisible = [m.event[0] for m in layout.moves if m.event and not _ecrivable(m.event[0])]
            if illisible:
                # Le DSL ne sait écrire ni `FRAGMENT NAME mon-domaine` ni
                # `AS @domains.mon-domaine.x` : convertir produirait un artefact qu'aucun
                # moteur ne charge. Le domaine se renomme dans la forge, et rien n'est perdu.
                raise WorkspaceConflictError("perimetre_non_ecrivable")
            for move in layout.moves:
                contenu = await copy.read(move.source)
                if contenu is None:
                    # Un chemin listé par git et illisible : on s'arrête AVANT d'écrire la
                    # moitié de la conversion. Passer outre laisserait un dépôt mélangé,
                    # c'est-à-dire précisément l'état qu'on refuse d'ouvrir ensuite.
                    raise WorkspaceConflictError("fichier_illisible")
                if move.event is not None:
                    contenu = normalized(contenu, *move.event)
                await copy.write(move.target, contenu)
                await copy.remove(move.source)
            await self._declare_converted(copy, layout)
            commit = await self.branches.commit(
                copy, f"Disposition : {len(layout.moves)} fichiers vers models/", author
            )
        await self._event(
            workspace_id,
            CONVERTED_EVENT,
            author,
            {"branch": copy.branch, "commit": commit, "moved": len(layout.moves)},
        )
        log.info(
            "disposition_convertie",
            workspace=workspace_id,
            branch=copy.branch,
            moved=len(layout.moves),
        )
        return len(layout.moves)

    async def _declare_converted(self, copy: WorkCopy, layout: Layout) -> None:
        """Déclare chaque ex-event dans l'artefact de son périmètre, à la suite de ce qui
        s'y trouve déjà.

        À la SUITE et non à la place : une branche peut porter des deux, si quelqu'un a
        déjà déclaré un type d'event à la main avant de convertir. Aucune clé d'unicité
        n'est posée, et c'est fidèle : `UNIQUE (…)` n'existait pas avant la déclaration, et
        en inventer une changerait l'anti-doublon d'un référentiel en service.
        """
        par_perimetre: dict[str, list[EventType]] = {}
        for scope, name in layout.event_types:
            titre = await _title(copy, scope, name)
            par_perimetre.setdefault(scope, []).append(EventType(name, titre, (scope, name)))
        for scope, ajoutes in par_perimetre.items():
            path = fragment_path(scope)
            texte = await copy.read(path)
            present = parse_fragment(texte) if texte else []
            deja = {declared.name for declared in present}
            nouveaux = [a for a in ajoutes if a.name not in deja]
            await copy.write(path, render(scope, [*present, *nouveaux]))

    async def _event(
        self, workspace_id: str, event_type: str, author: EventAuthor, properties: dict[str, Any]
    ) -> None:
        event = NewEvent(event_type, (ObjectRef("workspace", workspace_id),), author, properties)
        async with self.pool.acquire() as conn, conn.transaction():
            await db_write_event(conn, event, self.catalog, self.now)


def _ecrivable(scope: str) -> bool:
    return scope == SHARED or writable(scope)


async def _title(copy: WorkCopy, scope: str, name: str) -> str:
    """Le libellé d'un ex-event : le `title` de son schéma, son nom à défaut.

    Son nom à défaut, et non une chaîne vide : un libellé vide n'est pas écrivable dans le
    DSL (erreur de lexer, mesurée le 14/11/2026), donc un type d'event en a toujours un.
    """
    try:
        titre = parse_schema(await copy.read(model_path(scope, name)) or "").title
    except ValueError:
        # Retouché hors de Miles : on convertit quand même, sous le nom. Refuser ici
        # laisserait le dépôt entier inouvrable pour un seul fichier abîmé.
        titre = None
    return titre or name


def _summary(version: SavedVersion, branch: str) -> dict[str, Any]:
    return {
        "version": version.number,
        "commit": version.commit,
        "label": version.label,
        "branch": branch,
    }


def _label(label: str) -> str:
    # Une version sans libellé est inutilisable six mois plus tard, au moment précis où
    # on en a besoin (critère 5). Une ligne : il devient le sujet de l'étiquette.
    label = label.strip()
    if not label or len(label) > LABEL_MAX or "\n" in label:
        raise WorkspaceInputError("label")
    return label
