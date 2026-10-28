from __future__ import annotations

from pathlib import Path

from architecture.gardes import (
    GARDES_DE_CAMPAGNE,
    GARDES_DU_DEPLOIEMENT,
    file_appels,
    resolve_gardes_non_definies,
    resolve_gardes_perdues,
)

DEPOT = Path(__file__).resolve().parents[2]


def test_aucune_garde_de_deploiement_n_a_ete_perdue() -> None:
    perdues = resolve_gardes_perdues(DEPOT)
    assert not perdues, "gardes perdues :\n" + "\n".join(str(g) for g in perdues)


def test_toutes_les_gardes_attendues_sont_definies_au_socle() -> None:
    # Sans ce contrôle, renommer une fonction du socle ferait rougir les trois produits
    # sans dire que c'est la définition qui a bougé.
    assert resolve_gardes_non_definies(DEPOT) == ()


def test_la_lecture_des_appels_ignore_les_commentaires(tmp_path: Path) -> None:
    # Un script qui NOMME une garde dans une explication ne l'appelle pas : le test doit
    # voir la différence, sinon il suffirait d'en parler pour le satisfaire.
    script = tmp_path / "faux.sh"
    script.write_text(
        '# on pourrait appeler socle_port_libre ici\nsocle_sante "$PORT" 120\n',
        encoding="utf-8",
    )

    appels = file_appels(script)

    assert "socle_sante" in appels
    assert "socle_port_libre" not in appels


def test_une_garde_retiree_d_un_script_est_detectee(tmp_path: Path) -> None:
    # La faute pour de vrai : un produit qui n'appelle plus la sonde de port.
    for produit in ("portail", "enrolement", "environnement"):
        (tmp_path / produit / "scripts").mkdir(parents=True)
        reel = DEPOT / produit / "dev-deploy.sh"
        texte = reel.read_text(encoding="utf-8")
        if produit == "enrolement":
            texte = texte.replace("socle_port_libre", "# retiré")
        (tmp_path / produit / "dev-deploy.sh").write_text(texte, encoding="utf-8")
        (tmp_path / produit / "scripts" / "run-integration-tests.sh").write_text(
            (DEPOT / produit / "scripts" / "run-integration-tests.sh").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    perdues = resolve_gardes_perdues(tmp_path)

    assert [(g.produit, g.garde) for g in perdues] == [("enrolement", "socle_port_libre")]
    # Le message dit ce qu'on s'apprête à perdre, pas seulement qu'un nom manque.
    assert "notre propre service" in str(perdues[0])


def test_chaque_garde_attendue_porte_la_panne_qui_l_a_motivee() -> None:
    # Une liste de noms sans raison serait une liste qu'on élaguerait au premier refactor.
    for garde, panne in {**GARDES_DU_DEPLOIEMENT, **GARDES_DE_CAMPAGNE}.items():
        assert len(panne) > 40, f"{garde} : la raison est trop courte pour arrêter une main"
