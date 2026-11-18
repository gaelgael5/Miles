from __future__ import annotations

import pytest

from miles.datamodels.grammar import NAME_RE
from miles.datamodels.layout import (
    INBOUND,
    MODEL_RE,
    OUTBOUND,
    SHARED,
    ModelEntry,
    entry_of,
    model_path,
    visible,
)


@pytest.mark.parametrize(
    "reference",
    ["pudo/import-crm", "pudo/site", "shared/compte", "shared/compte_brut", "2a/3b"],
)
def test_a_declaration_may_designate_any_model_the_screen_can_create(reference: str) -> None:
    """Le motif suit NAME_RE : une copie à la main refusait « pudo/import-crm »."""
    scope, name = reference.split("/")
    assert NAME_RE.match(scope) and NAME_RE.match(name)
    assert MODEL_RE.match(reference) is not None


@pytest.mark.parametrize("reference", ["Pudo/Site", "pudo", "a/b/c", "/site", "pudo/", ""])
def test_what_is_not_a_model_reference_is_refused(reference: str) -> None:
    assert MODEL_RE.match(reference) is None


@pytest.mark.parametrize(
    ("path", "scope", "name"),
    [
        ("devices/inbound/transaction.yaml", INBOUND, "transaction"),
        ("devices/outbound/parametrage.yaml", OUTBOUND, "parametrage"),
    ],
)
def test_un_fichier_sous_un_sens_est_lu_comme_un_modele(path: str, scope: str, name: str) -> None:
    """Story 31025fe6 : sans cette lecture, un modèle device serait écrit par le portail
    et absent de sa propre liste — et la validation de branche ne le verrait pas non plus,
    puisqu'elle parcourt les mêmes entrées."""
    assert entry_of(path) == ModelEntry(scope, name, path)


@pytest.mark.parametrize(
    "path",
    [
        "devices/inbound/transaction.meta.yaml",
        "devices/inbound/.gitkeep",
        "devices/entrant/transaction.yaml",
        "devices/transaction.yaml",
    ],
)
def test_ce_qui_n_est_pas_un_modele_device_n_en_est_pas_un(path: str) -> None:
    # Les métadonnées portent la VERSION, pas un schéma : prises pour un modèle, elles
    # apparaîtraient dans la liste et la validation les lirait en JSON Schema.
    assert entry_of(path) is None


@pytest.mark.parametrize(
    ("depuis", "vers", "attendu"),
    [
        # Un modèle device voit les transverses et les devices de SON sens.
        ((INBOUND, "transaction"), (SHARED, "montant"), True),
        ((INBOUND, "transaction"), (INBOUND, "ligne"), True),
        # Jamais l'autre sens, ni un domaine : « chacun chez soi » (Gael, 23/10/2026).
        ((INBOUND, "transaction"), (OUTBOUND, "parametrage"), False),
        ((INBOUND, "transaction"), ("suivi", "colis"), False),
        # Et personne ne voit un device : ni un transverse, ni un modèle de domaine.
        ((SHARED, "montant"), (INBOUND, "transaction"), False),
        (("suivi", "colis"), (INBOUND, "transaction"), False),
    ],
)
def test_la_portee_d_un_modele_device_est_tenue_dans_LES_DEUX_SENS(
    depuis: tuple[str, str], vers: tuple[str, str], attendu: bool
) -> None:
    """Critère 3 de la story 31025fe6, éprouvé sur la règle elle-même.

    Les six cas ensemble, parce que c'est leur SYMÉTRIE qui est la règle : une règle qui
    n'interdirait que le sens « device vers domaine » laisserait un domaine dépendre d'un
    device, et le tuyau MQTT cesserait d'être commun à tous les domaines.
    """
    entry = ModelEntry(depuis[0], depuis[1], model_path(*depuis))
    assert visible(entry, vers) is attendu
