from __future__ import annotations

from pathlib import Path

from architecture.frontieres import file_paquets_de, resolve_violations

DEPOT = Path(__file__).resolve().parents[2]


def test_le_socle_n_importe_aucun_produit_et_aucun_produit_n_en_importe_un_autre() -> None:
    violations = resolve_violations(DEPOT)
    assert not violations, "frontières franchies :\n" + "\n".join(str(v) for v in violations)


def test_les_racines_lues_sont_bien_celles_du_depot() -> None:
    # Sans cette garde, un chemin devenu faux ferait passer le test précédent sur un
    # ensemble vide — le vert le plus trompeur qui soit.
    assert "miles_socle" in file_paquets_de(DEPOT / "socle" / "python" / "src")
    assert "miles" in file_paquets_de(DEPOT / "portail" / "backend" / "src")


def _depot_factice(racine: Path) -> None:
    socle = racine / "socle" / "python" / "src" / "miles_socle"
    produit = racine / "portail" / "backend" / "src" / "miles"
    for paquet in (socle, produit):
        paquet.mkdir(parents=True)
        (paquet / "__init__.py").write_text("", encoding="utf-8")


def test_un_import_interdit_du_socle_vers_le_produit_est_detecte(tmp_path: Path) -> None:
    # Critère 5 du ticket : un test de frontière qui ne peut pas échouer ne tient aucune
    # frontière. On introduit donc la faute pour de vrai au lieu de supposer qu'elle serait vue.
    _depot_factice(tmp_path)
    fautif = tmp_path / "socle" / "python" / "src" / "miles_socle" / "fautif.py"
    fautif.write_text("from miles.config import DatabaseSettings\n", encoding="utf-8")

    violations = resolve_violations(tmp_path)

    assert len(violations) == 1
    assert violations[0].racine == "socle"
    assert violations[0].importe == "miles"
    assert violations[0].ligne == 1


def test_un_produit_qui_importe_un_autre_produit_est_detecte(tmp_path: Path) -> None:
    _depot_factice(tmp_path)
    autre = tmp_path / "enrolement" / "backend" / "src" / "enrolement_app"
    autre.mkdir(parents=True)
    (autre / "__init__.py").write_text("", encoding="utf-8")
    fautif = tmp_path / "portail" / "backend" / "src" / "miles" / "fautif.py"
    fautif.write_text("import enrolement_app\n", encoding="utf-8")

    violations = resolve_violations(tmp_path)

    assert [(v.racine, v.importe) for v in violations] == [("portail", "enrolement_app")]


def test_un_produit_a_le_droit_d_importer_le_socle(tmp_path: Path) -> None:
    # La règle doit interdire le franchissement latéral sans interdire l'usage du socle,
    # qui est sa raison d'être.
    _depot_factice(tmp_path)
    licite = tmp_path / "portail" / "backend" / "src" / "miles" / "licite.py"
    licite.write_text("from miles_socle.auth import gate\n", encoding="utf-8")

    assert resolve_violations(tmp_path) == ()


def test_un_import_relatif_ne_franchit_jamais_une_frontiere(tmp_path: Path) -> None:
    _depot_factice(tmp_path)
    relatif = tmp_path / "socle" / "python" / "src" / "miles_socle" / "relatif.py"
    relatif.write_text("from . import autre\nfrom .db import pool\n", encoding="utf-8")

    assert resolve_violations(tmp_path) == ()
