from __future__ import annotations

from pathlib import Path

import pytest

from miles_socle.testing import (
    assert_harness_wires_everything,
    file_lifespan_wirings,
    file_wirings,
    resolve_missing_wirings,
)

APP = """
from contextlib import asynccontextmanager


def create_app():
    @asynccontextmanager
    async def lifespan(app):
        app.state.auth = object()
        app.state.secrets = object()
        app.state.cultures = object()
        yield

    return build_app(lifespan)


def build_app(lifespan=None):
    app = FastAPI(lifespan=lifespan)
    # Posé par build_app : tout montage de test qui l'appelle l'obtient par construction.
    app.state.signed_api_paths = frozenset()
    return app
"""
HARNAIS = """
def open_stack():
    app = build_app()
    app.state.auth = object()
    app.state.secrets = object()
    app.state.cultures = object()
    return app
"""


def _ecrire(tmp_path: Path, nom: str, source: str) -> Path:
    fichier = tmp_path / nom
    fichier.write_text(source, encoding="utf-8")
    return fichier


def test_les_services_de_la_duree_de_vie_sont_lus(tmp_path: Path) -> None:
    app = _ecrire(tmp_path, "app.py", APP)

    assert file_lifespan_wirings(app) == frozenset({"auth", "secrets", "cultures"})


def test_ce_que_pose_build_app_n_est_pas_compte(tmp_path: Path) -> None:
    # `signed_api_paths` est posé hors de la durée de vie : tout montage qui appelle
    # `build_app` l'obtient, et le comparer donnerait un manquant qui n'en est pas un.
    app = _ecrire(tmp_path, "app.py", APP)

    assert "signed_api_paths" in file_wirings(app)
    assert "signed_api_paths" not in file_lifespan_wirings(app)


def test_un_montage_complet_ne_manque_de_rien(tmp_path: Path) -> None:
    app = _ecrire(tmp_path, "app.py", APP)
    harnais = _ecrire(tmp_path, "stack.py", HARNAIS)

    assert resolve_missing_wirings(app, [harnais]) == frozenset()
    assert_harness_wires_everything(app, [harnais])


def test_un_service_oublie_dans_le_montage_est_nomme(tmp_path: Path) -> None:
    # La panne de LESSONS.md, reproduite : un service de plus dans l'application, et le
    # montage qui ne suit pas. C'est ce test qui prouve que la garde mord.
    app = _ecrire(
        tmp_path,
        "app.py",
        APP.replace("        yield", "        app.state.oidc = object()\n        yield"),
    )
    harnais = _ecrire(tmp_path, "stack.py", HARNAIS)

    assert resolve_missing_wirings(app, [harnais]) == frozenset({"oidc"})
    with pytest.raises(AssertionError, match="oidc"):
        assert_harness_wires_everything(app, [harnais])


def test_le_message_dit_quoi_faire_et_pointe_les_fichiers(tmp_path: Path) -> None:
    # Un refus qui ne dit pas quoi faire renvoie le travail à celui qui le lit.
    app = _ecrire(
        tmp_path,
        "app.py",
        APP.replace("        yield", "        app.state.oidc = object()\n        yield"),
    )
    harnais = _ecrire(tmp_path, "stack.py", HARNAIS)

    with pytest.raises(AssertionError) as refus:
        assert_harness_wires_everything(app, [harnais])

    message = str(refus.value)
    assert "app.py" in message
    assert "stack.py" in message
    assert "LESSONS.md" in message


def test_plusieurs_montages_se_completent(tmp_path: Path) -> None:
    # Le portail a trois montages, chacun partiel : c'est leur UNION qui doit couvrir.
    app = _ecrire(tmp_path, "app.py", APP)
    partiel_a = _ecrire(tmp_path, "a.py", "def f(app):\n    app.state.auth = 1\n")
    partiel_b = _ecrire(
        tmp_path, "b.py", "def g(app):\n    app.state.secrets = 1\n    app.state.cultures = 1\n"
    )

    assert resolve_missing_wirings(app, [partiel_a, partiel_b]) == frozenset()
    assert resolve_missing_wirings(app, [partiel_a]) == frozenset({"secrets", "cultures"})


def test_une_duree_de_vie_introuvable_leve_au_lieu_de_passer_au_vert(tmp_path: Path) -> None:
    # Le vert le plus trompeur : une garde qui ne compare rien et ne le dit pas.
    app = _ecrire(tmp_path, "app.py", APP)

    with pytest.raises(RuntimeError, match="introuvable"):
        file_lifespan_wirings(app, "duree_de_vie")


def test_un_nom_de_duree_de_vie_different_est_accepte(tmp_path: Path) -> None:
    app = _ecrire(tmp_path, "app.py", APP.replace("async def lifespan", "async def duree_de_vie"))

    assert file_lifespan_wirings(app, "duree_de_vie") == frozenset({"auth", "secrets", "cultures"})


def test_une_affectation_qui_n_est_pas_sur_app_state_est_ignoree(tmp_path: Path) -> None:
    source = "def f(app, autre):\n    autre.chose = 1\n    app.state.auth = 1\n    x.y = 2\n"
    fichier = _ecrire(tmp_path, "divers.py", source)

    assert file_wirings(fichier) == frozenset({"auth"})


ALIAS = """
def wire(portal):
    state = portal.app.state
    state.secrets = object()
    state.cultures = object()
"""


def test_un_alias_local_de_state_est_reconnu(tmp_path: Path) -> None:
    # Le style du portail : `state = portal.app.state` puis `state.secrets = …`. Sans
    # cette reconnaissance, les vingt-quatre services de son harnais git passeraient pour
    # non câblés, et la garde crierait au loup à chaque exécution.
    fichier = _ecrire(tmp_path, "wire.py", ALIAS)

    assert file_wirings(fichier) == frozenset({"secrets", "cultures"})


def test_un_attribut_d_une_variable_quelconque_n_est_pas_pris_pour_un_service(
    tmp_path: Path,
) -> None:
    # `autre.secrets = …` n'est pas un câblage : sans cette distinction, la garde se
    # tairait sur un oubli parce qu'un objet sans rapport porte le même nom d'attribut.
    fichier = _ecrire(tmp_path, "faux.py", "def f(autre):\n    autre.secrets = 1\n")

    assert file_wirings(fichier) == frozenset()


def test_un_service_declare_absent_avec_sa_raison_est_admis(tmp_path: Path) -> None:
    app = _ecrire(tmp_path, "app.py", APP)
    harnais = _ecrire(
        tmp_path, "stack.py", HARNAIS.replace("    app.state.cultures = object()\n", "")
    )

    # Fermé par défaut, ouvert nommément : la raison vit à côté du nom.
    assert_harness_wires_everything(
        app, [harnais], absents_admis={"cultures": "aucun test d'intégration ne les lit"}
    )


def test_une_exception_sans_raison_est_refusee(tmp_path: Path) -> None:
    # Sinon la liste devient un endroit où faire taire sans rien expliquer.
    app = _ecrire(tmp_path, "app.py", APP)
    harnais = _ecrire(
        tmp_path, "stack.py", HARNAIS.replace("    app.state.cultures = object()\n", "")
    )

    with pytest.raises(AssertionError, match="sans raison"):
        assert_harness_wires_everything(app, [harnais], absents_admis={"cultures": "   "})


def test_une_exception_devenue_inutile_est_signalee(tmp_path: Path) -> None:
    # Un service disparu laisse une exception qui ferait taire un oubli futur sur un nom
    # recyclé : on la fait retirer.
    app = _ecrire(tmp_path, "app.py", APP)
    harnais = _ecrire(tmp_path, "stack.py", HARNAIS)

    with pytest.raises(AssertionError, match="inutiles"):
        assert_harness_wires_everything(app, [harnais], absents_admis={"disparu": "raison"})


def test_une_exception_ne_cache_pas_les_autres_oublis(tmp_path: Path) -> None:
    app = _ecrire(
        tmp_path,
        "app.py",
        APP.replace("        yield", "        app.state.oidc = object()\n        yield"),
    )
    harnais = _ecrire(
        tmp_path, "stack.py", HARNAIS.replace("    app.state.cultures = object()\n", "")
    )

    with pytest.raises(AssertionError, match="oidc"):
        assert_harness_wires_everything(app, [harnais], absents_admis={"cultures": "raison"})
