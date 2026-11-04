"""La lecture des versions d'un dépôt, sur de vrais dépôts git locaux.

Pas de doublure de git ici : ce qu'on vérifie est précisément ce que git rend — le format
de `for-each-ref`, ce qu'une étiquette légère ne porte pas, et ce qu'un dépôt récupéré
superficiellement ne permet pas. Une doublure aurait rendu ce qu'on croit, et c'est
justement la croyance qui s'est révélée fausse le 01/11/2026 sur le bundle.
"""

from __future__ import annotations

import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from miles_socle.git.access import GitAccess
from miles_socle.git.failures import GitAccessError, Reason
from miles_socle.git.runner import GitResult, run_git
from miles_socle.git.versions import fetch_versions
from miles_socle.secrets.model import Secret

TOKEN = GitAccess(token=Secret("jeton-sans-usage-en-local"))
AUTEUR = ("-c", "user.name=Alice", "-c", "user.email=alice@annuaire.invalid")


def _git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return out.stdout


def _etiquette(semence: Path, nom: str, libelle: str, branche: str | None = None) -> None:
    pieds = ("-m", f"Branche: {branche}") if branche else ()
    _git(*AUTEUR, "tag", "-a", nom, "-m", libelle, *pieds, cwd=semence)


def _forge(tmp_path: Path) -> str:
    """Un dépôt nu portant deux versions annotées, dont la seconde sur une branche fille."""
    nu, semence = tmp_path / "forge.git", tmp_path / "semence"
    _git("init", "-q", "--bare", "-b", "main", str(nu))
    _git("init", "-q", "-b", "main", str(semence))
    for i in (1, 2, 3):
        (semence / "f.txt").write_text(f"ligne {i}\n", encoding="utf-8")
        _git("add", "-A", cwd=semence)
        _git(*AUTEUR, "commit", "-q", "-m", f"c{i}", cwd=semence)
        if i == 1:
            _etiquette(semence, "version/1", "Première version")
        if i == 3:
            _etiquette(semence, "version/2", "Réseau ferroviaire", "back/reseau/atelier")
    _git("push", "-q", str(nu), "HEAD:refs/heads/main", "--tags", cwd=semence)
    return str(nu)


GitCommand = Callable[..., Awaitable[GitResult]]


def _dans(dossier: Path) -> GitCommand:
    dossier.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", str(dossier))
    return lambda *args: run_git(list(args), dossier, TOKEN)


async def test_versions_are_read_most_recent_first_with_label_author_and_branch(
    tmp_path: Path,
) -> None:
    url = _forge(tmp_path)

    versions = await fetch_versions(_dans(tmp_path / "cache"), url)

    assert [v.number for v in versions] == [2, 1]
    recente = versions[0]
    assert recente.label == "Réseau ferroviaire"
    assert recente.branch == "back/reseau/atelier"
    assert recente.author == "Alice <alice@annuaire.invalid>"
    assert len(recente.commit) == 40
    # Sans ligne de pied : c'est le cas des étiquettes d'avant les branches filles, et il
    # doit rendre None plutôt qu'une chaîne vide — qui se lirait comme une branche sans nom.
    assert versions[1].branch is None


async def test_a_repository_without_version_tag_yields_no_version(tmp_path: Path) -> None:
    nu, semence = tmp_path / "vide.git", tmp_path / "vide"
    _git("init", "-q", "--bare", "-b", "main", str(nu))
    _git("init", "-q", "-b", "main", str(semence))
    _git(*AUTEUR, "commit", "-q", "--allow-empty", "-m", "c1", cwd=semence)
    _git("push", "-q", str(nu), "HEAD:refs/heads/main", cwd=semence)

    # Et surtout : aucun refus. git échoue sur un fetch dont le motif ne trouve rien, et
    # c'est pour cela que la liste distante est lue d'abord.
    assert await fetch_versions(_dans(tmp_path / "cache"), str(nu)) == []


async def test_a_lightweight_tag_is_not_a_version(tmp_path: Path) -> None:
    url = _forge(tmp_path)
    semence = tmp_path / "semence"
    _git("tag", "version/9", cwd=semence)
    _git("push", "-q", url, "refs/tags/version/9", cwd=semence)

    # Elle ne porte ni libellé, ni auteur, ni date : la laisser passer afficherait une
    # version aux champs vides, indiscernable d'une version mal enregistrée.
    assert [v.number for v in await fetch_versions(_dans(tmp_path / "cache"), url)] == [2, 1]


async def test_a_tag_outside_the_convention_is_not_a_version(tmp_path: Path) -> None:
    url = _forge(tmp_path)
    semence = tmp_path / "semence"
    _etiquette(semence, "version/deux", "Numéro non chiffré")
    _git("push", "-q", url, "refs/tags/version/deux", cwd=semence)

    assert [v.number for v in await fetch_versions(_dans(tmp_path / "cache"), url)] == [2, 1]


async def test_a_version_removed_from_the_forge_disappears_from_a_persistent_copy(
    tmp_path: Path,
) -> None:
    url = _forge(tmp_path)
    git = _dans(tmp_path / "cache")
    assert len(await fetch_versions(git, url)) == 2

    _git("push", "-q", url, "--delete", "refs/tags/version/1", cwd=tmp_path / "semence")

    # --prune : la copie du module d'enrôlement est PERSISTANTE, et une étiquette retirée
    # de la forge y resterait listée comme version pour toujours.
    assert [v.number for v in await fetch_versions(git, url)] == [2]


async def test_a_complete_fetch_yields_a_bundle_the_other_side_can_open(tmp_path: Path) -> None:
    """La raison d'être de `depth=None`, mesurée le 01/11/2026 et gardée par ce test.

    Un bundle fabriqué depuis un dépôt récupéré en `--depth 1` **se crée sans erreur**
    puis échoue à l'ouverture : « did not send all necessary objects ». C'est le vert
    trompeur que ce test interdit de réintroduire — il mord sur le paramètre `depth`, et
    non sur la seule présence du bundle.
    """
    url = _forge(tmp_path)
    cache = tmp_path / "cache"
    git = _dans(cache)

    versions = await fetch_versions(git, url, depth=None)
    paquet = tmp_path / "v2.bundle"
    _git("bundle", "create", str(paquet), "version/2", cwd=cache)

    cible = tmp_path / "cible"
    _git("init", "-q", str(cible))
    _git("fetch", "-q", str(paquet), "+refs/tags/version/2:refs/tags/version/2", cwd=cible)
    recu = _git("rev-parse", "version/2^{commit}", cwd=cible).strip()
    assert recu == versions[0].commit


async def test_an_unreachable_repository_is_refused_with_its_reason(tmp_path: Path) -> None:
    with pytest.raises(GitAccessError) as refus:
        await fetch_versions(_dans(tmp_path / "cache"), str(tmp_path / "pas-de-depot.git"))

    # La RAISON et pas seulement l'échec : l'écran du module d'enrôlement en fait un
    # message, et « identifiants » ou « dépôt inexistant » n'appellent pas le même geste.
    assert refus.value.reason in (Reason.REPOSITORY_NOT_FOUND, Reason.FAILED)


def _comptant(git: GitCommand) -> tuple[GitCommand, list[str]]:
    """Le même lanceur, plus la liste des sous-commandes git réellement passées.

    On COMPTE les invocations plutôt que de chronométrer (critère 1 de l'enabler 782ce1e9) :
    un chronomètre sur une forge locale mesure quelques millisecondes dans tous les cas et
    resterait vert si le `fetch` revenait. Ce qui est économisé est un aller-retour réseau,
    et c'est son existence qu'il faut affirmer, pas sa durée.
    """
    appels: list[str] = []

    async def compte(*args: str) -> GitResult:
        appels.append(args[0])
        return await git(*args)

    return compte, appels


async def test_an_unchanged_forge_is_read_without_fetching_anything(tmp_path: Path) -> None:
    url = _forge(tmp_path)
    git = _dans(tmp_path / "cache")
    await fetch_versions(git, url)

    compte, appels = _comptant(git)
    versions = await fetch_versions(compte, url)

    assert "fetch" not in appels
    # Et la lecture rend quand même tout : l'économie porte sur le transfert, pas sur le
    # résultat. Un test qui ne vérifierait que l'absence de fetch passerait aussi si la
    # fonction avait cessé de rendre les versions.
    assert [v.number for v in versions] == [2, 1]


async def test_a_version_added_on_the_forge_is_fetched(tmp_path: Path) -> None:
    url = _forge(tmp_path)
    git = _dans(tmp_path / "cache")
    await fetch_versions(git, url)
    semence = tmp_path / "semence"
    _etiquette(semence, "version/3", "Troisième")
    _git("push", "-q", url, "refs/tags/version/3", cwd=semence)

    compte, appels = _comptant(git)
    versions = await fetch_versions(compte, url)

    assert "fetch" in appels
    assert [v.number for v in versions] == [3, 2, 1]


async def test_a_version_removed_on_the_forge_is_fetched_and_pruned(tmp_path: Path) -> None:
    """Le sens que la comparaison aurait pu perdre : une étiquette en MOINS (critère 4).

    Une comparaison écrite comme « y a-t-il du nouveau sur la forge » laisserait ce cas
    sans fetch, donc sans `--prune`, et la version supprimée resterait listée. C'est le
    seul des quatre critères qu'une implémentation plausible rate en silence.
    """
    url = _forge(tmp_path)
    git = _dans(tmp_path / "cache")
    await fetch_versions(git, url)
    _git("push", "-q", url, "--delete", "refs/tags/version/1", cwd=tmp_path / "semence")

    compte, appels = _comptant(git)
    versions = await fetch_versions(compte, url)

    assert "fetch" in appels
    assert [v.number for v in versions] == [2]


async def test_a_version_moved_on_the_forge_is_fetched(tmp_path: Path) -> None:
    """Même nom, autre objet : ni une entrée ni une sortie, mais un SHA qui change."""
    url = _forge(tmp_path)
    git = _dans(tmp_path / "cache")
    premier = (await fetch_versions(git, url))[0].commit
    semence = tmp_path / "semence"
    _git("tag", "-d", "version/2", cwd=semence)
    (semence / "f.txt").write_text("deplacee\n", encoding="utf-8")
    _git("add", "-A", cwd=semence)
    _git(*AUTEUR, "commit", "-q", "-m", "c4", cwd=semence)
    _etiquette(semence, "version/2", "Déplacée")
    _git("push", "-q", "--force", url, "refs/tags/version/2", cwd=semence)

    compte, appels = _comptant(git)
    versions = await fetch_versions(compte, url)

    assert "fetch" in appels
    assert versions[0].label == "Déplacée"
    assert versions[0].commit != premier
