from __future__ import annotations

from pathlib import Path

from architecture.credentials import (
    NOMS_PORTEURS_DE_CREDENTIAL,
    resolve_fuites,
    resolve_noms_inconnus_du_contrat,
)

DEPOT = Path(__file__).resolve().parents[2]


def test_aucun_credential_git_n_atteint_le_module_d_environnement() -> None:
    fuites = resolve_fuites(DEPOT)
    assert not fuites, "credentials git atteints par l'environnement :\n" + "\n".join(
        str(f) for f in fuites
    )


def test_les_noms_gardes_existent_toujours_au_contrat() -> None:
    # Sans ce contrôle, renommer une pièce du contrat laisserait la garde chercher un mot
    # que plus personne n'écrit — verte pour toujours, et pour rien.
    assert resolve_noms_inconnus_du_contrat(DEPOT) == ()


def test_une_reference_glissee_dans_l_environnement_est_detectee(tmp_path: Path) -> None:
    # La faute pour de vrai, et c'est celle que le ticket nomme : « la facilité qui se
    # présentera le jour où le relais sera lent » — un module d'environnement qui va
    # chercher le credential plutôt que de passer par le relais.
    source = tmp_path / "environnement" / "backend" / "src" / "environnement" / "git.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "from miles_socle.signing.protocol import GIT_CONNECTIONS_PATH\n",
        encoding="utf-8",
    )

    fuites = resolve_fuites(tmp_path)

    assert [(f.nom, f.ligne) for f in fuites] == [("GIT_CONNECTIONS_PATH", 1)]
    # Le message dit ce qu'on s'apprête à perdre, pas seulement qu'un mot a été trouvé.
    assert "s'apprête à en demander" in str(fuites[0])


def test_la_lecture_couvre_le_front_autant_que_le_backend(tmp_path: Path) -> None:
    # Le front d'un environnement peut appeler une route aussi bien que son backend : un
    # contrôle qui ne lirait que le Python laisserait passer la moitié du produit.
    source = tmp_path / "environnement" / "frontend" / "src" / "api" / "git.ts"
    source.parent.mkdir(parents=True)
    source.write_text('const p = "ConfidedGitConnection";\n', encoding="utf-8")

    fuites = resolve_fuites(tmp_path)

    assert [f.nom for f in fuites] == ["ConfidedGitConnection"]


def test_chaque_nom_garde_porte_la_raison_de_sa_garde() -> None:
    # Une garde sans sa raison finit par être retirée de bonne foi : c'est la règle de la
    # skill de déploiement, et elle vaut pour celle-ci.
    assert all(len(raison) > 40 for raison in NOMS_PORTEURS_DE_CREDENTIAL.values())
