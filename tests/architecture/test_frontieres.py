from __future__ import annotations

from pathlib import Path

from architecture.frontieres import (
    PAQUET_SOCLE_WEB,
    SOCLE_DEPLOY,
    file_extras_du_socle,
    file_paquets_de,
    file_racines_web,
    file_sources_shell,
    resolve_violations,
    resolve_violations_extras,
    resolve_violations_shell,
    resolve_violations_web,
)

DEPOT = Path(__file__).resolve().parents[2]


def test_le_socle_n_importe_aucun_produit_et_aucun_produit_n_en_importe_un_autre() -> None:
    violations = resolve_violations(DEPOT)
    assert not violations, "frontières franchies :\n" + "\n".join(str(v) for v in violations)


def test_les_racines_lues_sont_bien_celles_du_depot() -> None:
    # Sans cette garde, un chemin devenu faux ferait passer le test précédent sur un
    # ensemble vide — le vert le plus trompeur qui soit.
    assert "miles_socle" in file_paquets_de(DEPOT / "socle" / "python" / "src")
    assert "miles" in file_paquets_de(DEPOT / "portail" / "backend" / "src")
    assert "enrolement" in file_paquets_de(DEPOT / "enrolement" / "backend" / "src")
    assert "environnement" in file_paquets_de(DEPOT / "environnement" / "backend" / "src")


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


# --- Frontière côté TypeScript ---------------------------------------------------------


def test_aucun_front_ne_sort_de_sa_racine_par_un_chemin_relatif() -> None:
    violations = resolve_violations_web(DEPOT)
    assert not violations, "frontières franchies côté front :\n" + "\n".join(
        str(v) for v in violations
    )


def test_les_racines_front_lues_sont_bien_celles_du_depot() -> None:
    # Même garde que pour Python : un chemin devenu faux ferait passer le test précédent
    # sur un ensemble vide.
    noms = {racine.nom for racine in file_racines_web(DEPOT)}
    assert "socle-web" in noms
    assert "portail" in noms


def _front_factice(racine: Path) -> tuple[Path, Path]:
    socle = racine / "socle" / "web" / "src"
    produit = racine / "portail" / "frontend" / "src"
    for repertoire in (socle, produit):
        repertoire.mkdir(parents=True)
    return socle, produit


def test_un_produit_qui_atteint_le_socle_par_un_chemin_relatif_est_detecte(
    tmp_path: Path,
) -> None:
    _, produit = _front_factice(tmp_path)
    (produit / "App.tsx").write_text(
        'import { AuthGate } from "../../../socle/web/src/auth/AuthGate";\n', encoding="utf-8"
    )
    violations = resolve_violations_web(tmp_path)
    assert [(v.racine, v.importe) for v in violations] == [
        ("portail", "../../../socle/web/src/auth/AuthGate")
    ]


def test_un_produit_qui_atteint_le_front_d_un_autre_produit_est_detecte(tmp_path: Path) -> None:
    # La faute est posée dans l'AUTRE produit : le front du portail rendu par la fabrique
    # ne sert ici qu'à ce qu'il existe deux racines entre lesquelles franchir.
    _front_factice(tmp_path)
    autre = tmp_path / "enrolement" / "frontend" / "src"
    autre.mkdir(parents=True)
    (autre / "Menu.tsx").write_text(
        'import { WorkspacesNav } from "../../../portail/frontend/src/layout/WorkspacesNav";\n',
        encoding="utf-8",
    )
    violations = resolve_violations_web(tmp_path)
    assert [v.racine for v in violations] == ["enrolement"]


def test_le_socle_web_qui_atteint_un_produit_est_detecte(tmp_path: Path) -> None:
    socle, _ = _front_factice(tmp_path)
    (socle / "index.ts").write_text(
        'export * from "../../../portail/frontend/src/api/workspaces";\n', encoding="utf-8"
    )
    violations = resolve_violations_web(tmp_path)
    assert [v.racine for v in violations] == ["socle-web"]


def test_un_produit_consomme_le_socle_web_par_le_nom_de_son_paquet(tmp_path: Path) -> None:
    _, produit = _front_factice(tmp_path)
    (produit / "App.tsx").write_text(
        f'import {{ AuthGate }} from "{PAQUET_SOCLE_WEB}";\nimport "./styles.css";\n',
        encoding="utf-8",
    )
    assert resolve_violations_web(tmp_path) == ()


def test_les_scripts_shell_ne_franchissent_aucune_frontiere() -> None:
    violations = resolve_violations_shell(DEPOT)
    assert not violations, "frontières franchies :\n" + "\n".join(str(v) for v in violations)


def test_les_scripts_de_deploiement_sourcent_bien_les_gardes_du_socle() -> None:
    # Sans cette garde, la règle précédente passerait au vert sur un ensemble vide — par
    # exemple si les scripts cessaient de sourcer quoi que ce soit, ou si le motif de
    # lecture devenait faux.
    for produit in ("portail", "enrolement", "environnement"):
        script = DEPOT / produit / "dev-deploy.sh"
        cibles = [cible for cible, _ in file_sources_shell(script)]
        assert any(SOCLE_DEPLOY in cible for cible in cibles), f"{produit} ne source pas le socle"


def test_un_produit_qui_source_le_script_d_un_autre_est_detecte(tmp_path: Path) -> None:
    # La faute pour de vrai : un test de frontière qui ne peut pas échouer ne tient rien.
    (tmp_path / "portail").mkdir()
    (tmp_path / "enrolement").mkdir()
    fautif = tmp_path / "enrolement" / "dev-deploy.sh"
    fautif.write_text('source "$DEPOT_DIR/portail/dev-deploy.sh"\n', encoding="utf-8")

    violations = resolve_violations_shell(tmp_path)

    assert [(v.racine, v.importe) for v in violations] == [
        ("enrolement", '"$DEPOT_DIR/portail/dev-deploy.sh"')
    ]


def test_le_socle_qui_source_un_produit_est_detecte(tmp_path: Path) -> None:
    (tmp_path / "socle" / "deploy").mkdir(parents=True)
    fautif = tmp_path / "socle" / "deploy" / "gardes.sh"
    fautif.write_text('source "$DEPOT_DIR/portail/mosquitto/acl.sh"\n', encoding="utf-8")

    violations = resolve_violations_shell(tmp_path)

    assert [v.racine for v in violations] == ["socle"]


def test_sourcer_les_gardes_du_socle_est_licite(tmp_path: Path) -> None:
    # La règle doit interdire le franchissement latéral sans interdire le partage, qui est
    # sa raison d'être.
    (tmp_path / "environnement").mkdir()
    licite = tmp_path / "environnement" / "dev-deploy.sh"
    licite.write_text('source "$DEPOT_DIR/socle/deploy/gardes.sh"\n', encoding="utf-8")

    assert resolve_violations_shell(tmp_path) == ()


def test_un_produit_n_importe_un_sous_paquet_a_extra_du_socle_que_s_il_le_declare() -> None:
    violations = resolve_violations_extras(DEPOT)
    assert not violations, "extra du socle non déclaré :\n" + "\n".join(str(v) for v in violations)


def test_les_extras_du_socle_sont_bien_lus() -> None:
    # Sans cette garde, un `pyproject.toml` déplacé ferait passer le test précédent sur un
    # ensemble vide — et c'est précisément le vert trompeur que la règle doit éviter.
    extras = file_extras_du_socle(DEPOT)
    assert {"testing", "transform"} <= extras


def _depot_a_extra(racine: Path, declare: str) -> Path:
    """Un dépôt factice : un socle à extra `transform`, et un produit qui l'importe."""
    socle = racine / "socle" / "python"
    (socle / "src" / "miles_socle" / "transform").mkdir(parents=True)
    (socle / "pyproject.toml").write_text(
        '[project]\nname = "miles-socle"\n\n'
        '[project.optional-dependencies]\ntransform = [\n    "urban-json==0.2.1",\n]\n'
        "\n[build-system]\nrequires = []\n",
        encoding="utf-8",
    )
    src = racine / "enrolement" / "backend" / "src" / "enrolement"
    src.mkdir(parents=True)
    (racine / "enrolement" / "backend" / "pyproject.toml").write_text(
        f'[project]\nname = "x"\ndependencies = [\n    "{declare}",\n]\n', encoding="utf-8"
    )
    fautif = src / "service.py"
    fautif.write_text("from miles_socle.transform.engine import evaluate\n", encoding="utf-8")
    return fautif


def test_importer_un_sous_paquet_a_extra_sans_le_declarer_est_detecte(tmp_path: Path) -> None:
    # La faute pour de vrai, pas la supposition qu'elle serait vue : c'est elle qui fait
    # échouer un conteneur au démarrage alors que tout passe en local.
    fautif = _depot_a_extra(tmp_path, "miles-socle")

    violations = resolve_violations_extras(tmp_path)

    assert [(v.racine, v.importe) for v in violations] == [("enrolement", "miles_socle.transform")]
    assert violations[0].fichier == fautif.relative_to(tmp_path)


def test_importer_un_sous_paquet_a_extra_en_le_declarant_est_licite(tmp_path: Path) -> None:
    # La règle doit interdire l'oubli sans interdire l'usage, qui est sa raison d'être.
    _depot_a_extra(tmp_path, "miles-socle[transform]")

    assert resolve_violations_extras(tmp_path) == ()
