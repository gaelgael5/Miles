from __future__ import annotations

from pathlib import Path

from architecture.campagnes import (
    ETIQUETTE,
    PRODUITS,
    file_lancements,
    resolve_lancements_sans_prise,
)

DEPOT = Path(__file__).resolve().parents[2]


def test_chaque_docker_run_de_campagne_est_nomme_et_etiquete() -> None:
    anomalies = resolve_lancements_sans_prise(DEPOT)
    assert not anomalies, "lancements hors de portée du piège :\n" + "\n".join(
        str(a) for a in anomalies
    )


def test_les_trois_produits_sont_bien_lus() -> None:
    # Sans ce contrôle, un chemin de script devenu faux rendrait le test ci-dessus
    # définitivement vert : il ne lirait plus rien.
    for produit in PRODUITS:
        lancements = file_lancements(DEPOT / produit / "scripts" / "run-integration-tests.sh")
        assert lancements, f"aucun `docker run` lu dans {produit}"


def test_une_etiquette_posee_sur_la_deuxieme_ligne_compte(tmp_path: Path) -> None:
    # La forme réelle des scripts : la commande tient sur plusieurs lignes. Une lecture
    # ligne à ligne déclarerait l'étiquette absente et ferait rougir du code correct.
    script = tmp_path / "portail" / "scripts" / "run-integration-tests.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        'docker run --rm --name "$RUN_ID-pytest" \\\n  ' + ETIQUETTE + ' \\\n  "$RUN_ID-backend"\n',
        encoding="utf-8",
    )

    assert resolve_lancements_sans_prise(tmp_path) == ()


def test_un_lancement_anonyme_est_detecte(tmp_path: Path) -> None:
    # La faute pour de vrai, celle du 22/11/2026 : un `--rm` sans nom ni étiquette.
    script = tmp_path / "enrolement" / "scripts" / "run-integration-tests.sh"
    script.parent.mkdir(parents=True)
    script.write_text(
        'docker run --rm --network "$RUN_ID" "$RUN_ID-backend" -m integration\n', encoding="utf-8"
    )

    anomalies = resolve_lancements_sans_prise(tmp_path)

    assert [a.manque for a in anomalies] == [
        "aucun nom dérivé de $RUN_ID",
        "aucune étiquette miles-campagne=$RUN_ID",
    ]
    assert anomalies[0].ligne == 1


def test_un_docker_run_seulement_commente_ne_compte_pas(tmp_path: Path) -> None:
    # Un script qui cite un `docker run` dans une explication n'en lance pas : sinon un
    # commentaire suffirait à faire rougir, et le test se ferait retirer.
    script = tmp_path / "portail" / "scripts" / "run-integration-tests.sh"
    script.parent.mkdir(parents=True)
    script.write_text("# avant, on faisait docker run --rm sans nom\n", encoding="utf-8")

    assert file_lancements(script) == ()
