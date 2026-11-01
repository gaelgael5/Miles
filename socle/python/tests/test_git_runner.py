"""Le lanceur git : ce qu'il pose, et ce qu'il ne pose SURTOUT pas.

Les trois garanties de ce lanceur tiennent chacune à une ligne, et aucune ne se voit à la
lecture d'un appel : le jeton n'entre pas dans les arguments (que `ps auxww` lit), il
n'est pas écrit sur disque, et il ne remonte pas dans la sortie rendue. S'y ajoute depuis
le 01/11/2026 le cas du module d'environnement, qui lance git SANS aucun credential.
"""

from __future__ import annotations

from pathlib import Path

from miles_socle.git.access import GitAccess
from miles_socle.git.runner import run_git
from miles_socle.secrets.model import Secret

JETON = "pat-de-test-qui-ne-doit-jamais-sortir"  # valeur d'essai


async def _helpers(tmp_path: Path, access: GitAccess | None) -> list[str]:
    """Les assistants d'identifiants que git voit RÉELLEMENT, lus de git lui-même."""
    lu = await run_git(["config", "--get-all", "credential.helper"], tmp_path, access)
    return lu.stdout.splitlines()


async def test_sans_credential_aucun_assistant_n_est_pose(tmp_path: Path) -> None:
    """C'est le cas du module d'environnement, et l'interdit central du ticket edcf78bc.

    La ligne vide n'est pas un assistant : c'est l'EFFACEMENT de ceux que la machine
    pourrait avoir configurés. Sans elle, un git lancé sans jeton en trouverait un dans
    la configuration de l'hôte, et le secret serait revenu par la porte de derrière.
    """
    assert await _helpers(tmp_path, None) == [""]


async def test_avec_credential_un_seul_assistant_est_pose_apres_l_effacement(
    tmp_path: Path,
) -> None:
    helpers = await _helpers(tmp_path, GitAccess(token=Secret(JETON)))

    # L'effacement d'abord, l'assistant ensuite, et dans cet ordre : posé avant, il serait
    # effacé par le suivant et git redemanderait les identifiants au terminal.
    assert helpers[0] == ""
    assert len(helpers) == 2
    # Le jeton n'est PAS dans la définition de l'assistant : celui-ci le lit dans
    # l'environnement du seul processus git. Ce qui est ici est lisible par `ps auxww`.
    assert JETON not in helpers[1]
    assert "MILES_GIT_TOKEN" in helpers[1]


async def test_le_jeton_est_masque_s_il_revient_dans_la_sortie(tmp_path: Path) -> None:
    """Une forge pourrait le renvoyer en écho ; il ne doit jamais atteindre un journal.

    Éprouvé en le faisant écrire par git lui-même sur sa sortie, ce qui est le seul moyen
    de vérifier le masquage sans dépendre d'une forge complaisante.
    """
    # git RECOPIE la valeur qu'on lui donne : c'est le seul moyen de faire écrire le
    # jeton sur la sortie sans dépendre d'une forge complaisante. Un `--get` sur une clé
    # absente n'aurait rien écrit, et le test serait passé sans rien mesurer.
    echo = await run_git(
        ["-c", f"essai.jeton={JETON}", "config", "--get", "essai.jeton"],
        tmp_path,
        GitAccess(token=Secret(JETON)),
    )

    assert echo.ok, echo.stderr
    assert JETON not in echo.stdout
    assert echo.stdout.strip() == "********"


async def test_sans_jeton_la_sortie_n_est_pas_decoupee(tmp_path: Path) -> None:
    """Remplacer la chaîne vide dans la sortie l'aurait hachée caractère par caractère.

    Le cas se présente dès qu'on lance git sans credential, donc à chaque geste du module
    d'environnement : sans la garde, tout message de git deviendrait illisible.
    """
    version = await run_git(["--version"], tmp_path, None)

    assert version.ok
    assert version.stdout.startswith("git version")
