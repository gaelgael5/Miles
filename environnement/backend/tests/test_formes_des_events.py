from __future__ import annotations

import pytest
from miles_socle.events.model import EventAuthor, EventError, NewEvent, ObjectRef

from environnement.event_types import code_event_catalog
from environnement.hosting import model as hosting_events
from environnement.ingestion import model as ingestion_events

# Ce que des HELPERS d'écriture ajoutent au bloc, en plus de ce que le site d'appel passe.
# C'est la cause exacte de la panne du 12/11/2026 : les formes de `hosting.version_served`
# et `hosting.version_refused` avaient été mesurées sur le site d'appel — `{"commit": …}` —
# alors que `HostingService._write_event` complète chaque bloc avec l'ordre reçu. Le
# catalogue a donc refusé TOUS les events de ce module, et c'est la campagne d'intégration
# qui l'a dit, dix minutes plus tard et après un déploiement.
#
# Cette table est ce qui rend la panne impossible à refaire : chaque entrée nomme un helper
# et ce qu'il injecte, et le test exige que les types qu'il écrit le déclarent. Elle se
# complète le jour où un helper se met à injecter autre chose — et c'est exactement ce
# qu'on veut, parce qu'alors le test rougit avant la campagne.
INJECTE: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "HostingService._write_event",
        hosting_events.EVENT_TYPES_ORDONNES,
        ("number", "ordered_commit"),
    ),
)


AUTEUR = EventAuthor("local", "admin")


def _event(event_type: str, proprietes: dict[str, object]) -> NewEvent:
    return NewEvent(event_type, (ObjectRef("hosted_version", "w1"),), AUTEUR, proprietes)


class TestCeQueLesHelpersAjoutentEstDeclare:
    """Un helper qui complète le bloc et un type qui ne le déclare pas = tous ses events
    refusés. Le bloc étant FERMÉ, le refus est total et immédiat."""

    @pytest.mark.parametrize(("helper", "types", "ajoutees"), INJECTE, ids=lambda v: str(v)[:40])
    def test_les_types_ecrits_par_un_helper_declarent_ce_qu_il_ajoute(
        self, helper: str, types: tuple[str, ...], ajoutees: tuple[str, ...]
    ) -> None:
        catalogue = code_event_catalog()

        for nom in types:
            declarees = set(catalogue.of(nom).block.get("properties") or {})
            manquantes = sorted(set(ajoutees) - declarees)
            assert not manquantes, f"{helper} ajoute {manquantes} à {nom}, non déclaré"

    def test_les_types_ecrits_par_un_helper_les_exigent(self) -> None:
        """Déclarées ET obligatoires : le helper les ajoute à CHAQUE event, donc un event
        qui ne les porterait pas serait un event que ce code ne peut pas produire."""
        catalogue = code_event_catalog()

        for _helper, types, ajoutees in INJECTE:
            for nom in types:
                exigees = set(catalogue.of(nom).block.get("required") or ())
                assert set(ajoutees) <= exigees, nom


class TestCeQueLaCampagneAvaitTrouve:
    """Les deux blocs que la campagne du 12/11/2026 a refusés, éprouvés ici en quatre
    millisecondes au lieu de dix minutes."""

    def test_une_version_servie_porte_l_ordre_recu_en_plus_du_commit_servi(self) -> None:
        """`commit` est ce qu'on SERT, `ordered_commit` ce qui avait été demandé : les deux,
        parce que le refus `commit_inattendu` existe précisément quand ils diffèrent."""
        code_event_catalog().check_event(
            _event(
                hosting_events.VERSION_SERVED_EVENT,
                {"number": 3, "ordered_commit": "a" * 40, "commit": "a" * 40},
            )
        )

    def test_une_version_refusee_porte_l_ordre_recu_en_plus_du_motif(self) -> None:
        code_event_catalog().check_event(
            _event(
                hosting_events.VERSION_REFUSED_EVENT,
                {"number": 3, "ordered_commit": "b" * 40, "refusal": "relais_injoignable"},
            )
        )

    def test_un_depot_de_fichier_porte_sa_taille_et_les_autres_modes_leur_compte(self) -> None:
        """Le seul type de Miles dont le bloc dépend d'une de ses propriétés, et il a DEUX
        producteurs : le dépôt de fichier et les modes élément et tableau."""
        catalogue = code_event_catalog()
        communs = {"source": "colis", "entry_model": "colis_v1", "key_label": "clé de test"}

        catalogue.check_event(
            _event(
                ingestion_events.RECEIVED_EVENT,
                {**communs, "mode": ingestion_events.FILE, "storage": "colis", "size_bytes": 12},
            )
        )
        catalogue.check_event(
            _event(
                ingestion_events.RECEIVED_EVENT,
                {**communs, "mode": ingestion_events.BATCH, "object_count": 7},
            )
        )
        # Discriminant : un dépôt de fichier SANS sa taille est refusé, et c'est ce qu'on
        # lit en premier quand une ingestion est lente.
        with pytest.raises(EventError, match="size_bytes"):
            catalogue.check_event(
                _event(
                    ingestion_events.RECEIVED_EVENT,
                    {**communs, "mode": ingestion_events.FILE, "storage": "colis"},
                )
            )
