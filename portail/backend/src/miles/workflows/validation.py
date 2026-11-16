"""Ce qu'un script de workflow doit vérifier pour qu'une version puisse être figée.

Trois manquements, et chacun rend le répertoire INCHARGEABLE pour le moteur — c'est le
critère : on ne bloque pas une version sur une préférence de style.

- le script ne se relit pas : `load_directory` appelle `parser.check()` sur TOUS les
  fichiers du répertoire avant d'en visiter un seul, donc un script cassé empêche le
  chargement des autres ;
- son `NAME` ne correspond pas à son fichier : le moteur s'en moque, mais plus personne
  ne retrouve le script que ses pairs nomment — et la liste de l'atelier désignerait l'un
  ou l'autre en mentant sur le second ;
- un `INCLUDE` ne désigne aucun artefact de la branche : mesuré, le chargeur lève
  `FileNotFoundError(f"missing file {include}")`.
"""

from __future__ import annotations

from pathlib import Path

from miles.datamodels.grammar import Problem
from miles.git.workcopy import WorkCopy
from miles.workflowevents.dsl import fragment_path, scope_of
from miles.workflows.dsl import ScriptError, read_header
from miles.workflows.layout import names_in, workflow_path


async def workflow_reports(
    copy: WorkCopy, paths: list[str]
) -> list[tuple[str, tuple[Problem, ...]]]:
    """Chaque script de workflow de la branche, relu avec le parseur du moteur.

    Mêmes vérifications qu'à l'écriture par Miles : un script retouché dans GitHub ne se
    fige pas en version si le moteur ne saurait pas le charger.
    """
    available = _fragment_files(paths)
    reports: list[tuple[str, tuple[Problem, ...]]] = []
    for name in names_in(paths):
        path = workflow_path(name)
        found = await _problems(copy, path, name, available)
        if found:
            reports.append((path, found))
    return reports


async def _problems(
    copy: WorkCopy, path: str, name: str, available: set[str]
) -> tuple[Problem, ...]:
    try:
        header = read_header(await copy.read(path) or "")
    except ScriptError as exc:
        # Un manquement par erreur du parseur, positionné comme le moteur le positionne :
        # un seul « script invalide » ferait rouvrir le fichier pour chercher où.
        return tuple(
            Problem("", "script_invalide", f"{p.line}:{p.column} {p.message}") for p in exc.problems
        )
    found = []
    if header.name != name:
        found.append(Problem("", "nom_different_du_fichier", header.name))
    found += [
        Problem("includes", "include_introuvable", include)
        for include in header.includes
        if include not in available
    ]
    return tuple(found)


def _fragment_files(paths: list[str]) -> set[str]:
    """Les noms de FICHIER qu'un `INCLUDE` peut désigner sur cette branche.

    Des noms de fichier et non des chemins, parce que c'est ce qu'un `INCLUDE` écrit et
    ce que `dsl.loader.load_directory` indexe (« par chemin complet ET par nom de fichier
    seul »). Dérivés des artefacts RÉELLEMENT présents : un périmètre sans aucun type
    d'event n'a pas d'artefact, et l'inclure échouerait.
    """
    scopes = [scope for path in paths if (scope := scope_of(path)) is not None]
    return {Path(fragment_path(scope)).name for scope in scopes}
