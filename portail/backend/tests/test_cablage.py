from __future__ import annotations

from pathlib import Path

from miles_socle.testing import assert_harness_wires_everything

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "src" / "miles" / "app.py"
INTEGRATION = BACKEND / "tests" / "integration"


def test_tout_service_pose_par_l_application_est_cable_dans_la_suite_d_integration() -> None:
    """La garde que `LESSONS.md` réclamait, après deux occurrences de la même panne ICI.

    Un service ajouté dans `app.py` et oublié dans le montage des tests d'intégration fait
    tomber TOUS les tests de ce service, sur une erreur qui ne parle pas de lui : 22 tests
    rouges le 22/10/2026 avec la story 7fa00f56, 15 le 24/10 avec les storages. Ici l'oubli
    fait rougir un seul test, qui nomme le service manquant.

    Ce que cette garde couvre s'est RÉTRÉCI, et c'est un progrès : les sept services du
    socle sont désormais posés par `wire_socle_services`, que la production et les harnais
    de test appellent tous les deux — les oublier n'est plus exprimable. Ne reste donc à
    garder que ce que ce produit ajoute lui-même, et c'est là qu'était le risque.

    Elle portait jusqu'au 28/10/2026 une exception pour `health_probe`, qu'aucun test
    d'intégration du portail ne câblait. Le socle le câble maintenant, et l'exception est
    tombée d'elle-même — c'est la garde qui l'a signalée comme devenue inutile.

    La suite d'intégration est lue EN ENTIER, pas seulement les trois harnais : cette suite
    câble dans chaque test ce dont il a besoin, et un service câblé là compte comme câblé.
    """
    assert_harness_wires_everything(APP, sorted(INTEGRATION.glob("*.py")))


def test_la_garde_lit_bien_les_fichiers_du_produit() -> None:
    # Sans cette vérification, un chemin devenu faux ferait passer le test précédent sur
    # un ensemble vide — le vert le plus trompeur qui soit.
    assert APP.is_file()
    assert INTEGRATION.is_dir()
    assert len(sorted(INTEGRATION.glob("*.py"))) > 30
