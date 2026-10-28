from __future__ import annotations

from pathlib import Path

from miles_socle.testing import assert_harness_wires_everything

BACKEND = Path(__file__).resolve().parents[1]
APP = BACKEND / "src" / "miles" / "app.py"
INTEGRATION = BACKEND / "tests" / "integration"
# Services que la durée de vie pose et qu'aucun test d'intégration n'a à câbler, avec leur
# raison. Liste FERMÉE par défaut : un service ajouté demain et oublié fait rougir le test,
# et pour le taire il faut l'écrire ici — donc le décider, pas l'oublier.
ABSENTS_ADMIS = {
    "health_probe": (
        "la route de santé est couverte par les tests unitaires (une sonde d'essai y "
        "répond) ; aucun test d'intégration du portail ne l'interroge, et câbler une "
        "sonde que personne ne lit mettrait du code mort dans le harnais. Constaté le "
        "28/10/2026 en posant cette garde."
    ),
}


def test_tout_service_pose_par_l_application_est_cable_dans_la_suite_d_integration() -> None:
    """La garde que `LESSONS.md` réclamait, après deux occurrences de la même panne ICI.

    Un service ajouté dans `app.py` et oublié dans le montage des tests d'intégration fait
    tomber TOUS les tests de ce service, sur une erreur qui ne parle pas de lui : 22 tests
    rouges le 22/10/2026 avec la story 7fa00f56, 15 le 24/10 avec les storages. Ici l'oubli
    fait rougir un seul test, qui nomme le service manquant.

    La suite d'intégration est lue EN ENTIER, pas seulement les trois harnais : cette suite
    câble dans chaque test ce dont il a besoin, et un service câblé là compte comme câblé.
    """
    assert_harness_wires_everything(
        APP, sorted(INTEGRATION.glob("*.py")), absents_admis=ABSENTS_ADMIS
    )


def test_la_garde_lit_bien_les_fichiers_du_produit() -> None:
    # Sans cette vérification, un chemin devenu faux ferait passer le test précédent sur
    # un ensemble vide — le vert le plus trompeur qui soit.
    assert APP.is_file()
    assert INTEGRATION.is_dir()
    assert len(sorted(INTEGRATION.glob("*.py"))) > 30
