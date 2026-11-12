from __future__ import annotations

import pytest
from miles_socle.events.model import EventAuthor, EventError, NewEvent, ObjectRef

from miles.event_types import code_event_catalog
from miles.workshop import trads_keys as trads_keys_events
from miles.workshop import trads_service as trads_events

AUTEUR = EventAuthor("local", "admin")
# Ce que des HELPERS d'écriture ajoutent au bloc, en plus de ce que le site d'appel passe.
# C'est la cause de la panne du 12/11/2026 : des formes mesurées sur le site d'appel, alors
# qu'un helper complétait le bloc. Le bloc étant FERMÉ, le refus est total et immédiat, et
# c'est la campagne d'intégration qui l'a dit — dix minutes et un déploiement plus tard.
# Chaque module nomme ce que son helper ajoute ; cette table ne le recopie pas.
INJECTE: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "TradsKeys._event",
        tuple(sorted(trads_keys_events.EVENT_TYPES)),
        trads_keys_events.AJOUTE_PAR_LE_HELPER,
    ),
    (
        "TradsService._event",
        tuple(sorted(trads_events.EVENT_TYPES)),
        trads_events.AJOUTE_PAR_LE_HELPER,
    ),
)


def _event(event_type: str, proprietes: dict[str, object]) -> NewEvent:
    return NewEvent(event_type, (ObjectRef("workspace", "w1"),), AUTEUR, proprietes)


class TestCeQueLesHelpersAjoutentEstDeclare:
    @pytest.mark.parametrize(("helper", "types", "ajoutees"), INJECTE, ids=lambda v: str(v)[:30])
    def test_les_types_ecrits_par_un_helper_declarent_et_exigent_ce_qu_il_ajoute(
        self, helper: str, types: tuple[str, ...], ajoutees: tuple[str, ...]
    ) -> None:
        catalogue = code_event_catalog()

        for nom in types:
            bloc = catalogue.of(nom).block
            declarees = set(bloc.get("properties") or {})
            exigees = set(bloc.get("required") or ())
            assert set(ajoutees) <= declarees, f"{helper} ajoute à {nom} sans déclaration"
            # Obligatoires : le helper les ajoute à CHAQUE event, donc un event qui ne les
            # porterait pas serait un event que ce code ne peut pas produire.
            assert set(ajoutees) <= exigees, f"{helper} : {nom} ne les exige pas"


class TestCeQueLaCampagneAvaitTrouve:
    """Le bloc que la campagne du 12/11/2026 a refusé, éprouvé ici en millisecondes."""

    def test_la_suppression_d_une_cle_compte_les_cultures_et_ne_les_liste_pas(self) -> None:
        """`cultures` est le NOMBRE de fichiers de cultures dont la valeur a disparu — la
        première version de cette forme avait supposé une liste. Au moins un : zéro
        culture touchée lève `KeyUnknownError` avant d'écrire l'event."""
        catalogue = code_event_catalog()
        bloc = {"key": "accueil_titre", "context": "caisse", "branch": "work/alice", "cultures": 2}

        catalogue.check_event(_event(trads_keys_events.KEY_DELETED_EVENT, bloc))

        with pytest.raises(EventError, match=r"\$\.cultures"):
            catalogue.check_event(
                _event(trads_keys_events.KEY_DELETED_EVENT, {**bloc, "cultures": ["fr-FR"]})
            )
        with pytest.raises(EventError, match=r"\$\.cultures"):
            catalogue.check_event(
                _event(trads_keys_events.KEY_DELETED_EVENT, {**bloc, "cultures": 0})
            )
