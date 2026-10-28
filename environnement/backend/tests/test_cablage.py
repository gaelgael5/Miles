from __future__ import annotations

from pathlib import Path

from miles_socle.testing import assert_harness_wires_everything

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "src" / "environnement" / "app.py"
INTEGRATION = BACKEND / "tests" / "integration"


def test_tout_service_pose_par_l_application_est_cable_dans_la_suite_d_integration() -> None:
    """La garde que `LESSONS.md` réclamait, après deux occurrences de la même panne.

    Un service ajouté dans `app.py` et oublié dans le montage des tests d'intégration fait
    tomber TOUS les tests de ce service, sur une erreur qui ne parle pas de lui : 22 tests
    rouges le 22/10/2026, 15 le 24/10. Ici l'oubli fait rougir un seul test, qui nomme le
    service manquant.

    Ce que cette garde couvre s'est RÉTRÉCI le 28/10/2026, et c'est un progrès : les sept
    services du socle sont posés par `wire_socle_services`, que la production et le harnais
    de test appellent tous les deux — les oublier n'est plus exprimable. Ne reste donc à
    garder que ce que ce produit ajoute lui-même, et c'est là qu'était le risque.

    La suite d'intégration est lue EN ENTIER, pas seulement le harnais : un service câblé
    dans un test compte comme câblé. La garde répond donc exactement à la question qui
    importe — « un test d'intégration peut-il employer ce service ? » — et pas à une
    question plus stricte dont la réponse dépendrait du style de la suite.
    """
    assert_harness_wires_everything(APP, sorted(INTEGRATION.glob("*.py")))


def test_la_garde_lit_bien_les_fichiers_du_produit() -> None:
    # Sans cette vérification, un chemin devenu faux ferait passer le test précédent sur
    # un ensemble vide — le vert le plus trompeur qui soit.
    assert APP.is_file()
    assert INTEGRATION.is_dir()
    assert len(sorted(INTEGRATION.glob("*.py"))) > 1
