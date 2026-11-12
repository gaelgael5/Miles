from __future__ import annotations

from typing import Any

import pytest
from miles_socle.cultures import service as cultures_events
from miles_socle.events.model import EventAuthor, EventError, NewEvent, ObjectRef
from miles_socle.oidc import service as oidc_events
from miles_socle.secrets import service as secrets_events
from miles_socle.signing import identity_model as module_identity_events

from enrolement.environments import model as environment_events
from enrolement.event_types import code_event_catalog
from enrolement.hosting import model as hosting_events
from enrolement.pairing import events as pairing_events

AUTEUR = EventAuthor("local", "admin")
MODULES = (
    cultures_events,
    oidc_events,
    secrets_events,
    module_identity_events,
    pairing_events,
    environment_events,
    hosting_events,
)


def _event(event_type: str, proprietes: dict[str, Any]) -> NewEvent:
    return NewEvent(event_type, (ObjectRef("environment", "e1"),), AUTEUR, proprietes)


class TestLeCatalogueDuCode:
    """Le produit déclare la FORME de ses types, et non plus leur seul nom.

    Construire le catalogue suffit à éprouver les refus de chargement : un doublon, un
    bloc qui n'est pas un objet, un bloc qui redéclare un champ de la racine commune ou un
    schéma invalide feraient échouer chacun de ces tests au premier appel.
    """

    def test_il_porte_tous_les_types_des_modules_et_rien_d_autre(self) -> None:
        attendus: set[str] = set()
        for module in MODULES:
            attendus |= module.EVENT_TYPES

        assert code_event_catalog().names() == attendus
        # Discriminant : un module oublié dans `event_types.py` ferait un catalogue plus
        # court, et l'égalité ci-dessus le dirait — mais pas un module compté deux fois.
        assert len(attendus) == 31

    def test_chaque_module_derive_ses_types_de_ses_formes(self) -> None:
        """Une seule liste par module, et c'est celle des formes.

        Deux listes auraient divergé au premier type ajouté : la plus courte aurait fait
        refuser au journal un event que le module écrit, et le défaut se serait découvert
        sur un geste métier choisi au hasard par le trafic.
        """
        for module in MODULES:
            assert module.EVENT_TYPES == frozenset(f.name for f in module.EVENT_SHAPES), module

    def test_tout_est_introduit_par_le_module_d_enrolement(self) -> None:
        catalogue = code_event_catalog()

        for nom in catalogue.names():
            categorie = catalogue.of(nom).category
            assert (categorie.number, categorie.slug) == (1, "backoffice-enrolement"), nom
            # Code : l'IHM de configuration les montrera en lecture seule.
            assert categorie.code_introduced

    def test_chaque_type_porte_un_libelle_propre(self) -> None:
        """Distincts, parce qu'un libellé recopié est la trace d'une forme recopiée — et
        une forme recopiée décrit le bloc d'un autre type que le sien."""
        catalogue = code_event_catalog()
        libelles = [catalogue.of(nom).label for nom in sorted(catalogue.names())]

        assert all(libelle.strip() for libelle in libelles)
        assert len(set(libelles)) == len(libelles)


class TestCeQueLesBlocsRefusent:
    """Les décisions qui vivent dans les schémas, éprouvées une par une.

    Chacune est une décision du producteur, pas un détail de forme : si l'un de ces tests
    rougit, c'est qu'une décision a changé et qu'il faut la relire, pas la contourner.
    """

    def test_un_bloc_conforme_passe(self) -> None:
        code_event_catalog().check_event(
            _event(
                hosting_events.VERSION_ORDERED_EVENT,
                {"workspace_id": "w1", "number": 3, "commit": "a" * 40, "label": "v3"},
            )
        )

    def test_une_propriete_obligatoire_absente_est_nommee(self) -> None:
        with pytest.raises(EventError, match="commit"):
            code_event_catalog().check_event(
                _event(
                    hosting_events.VERSION_ORDERED_EVENT,
                    {"workspace_id": "w1", "number": 3, "label": "v3"},
                )
            )

    def test_un_commit_abrege_est_refuse(self) -> None:
        """La forme du CHECK de la migration 0017, dérivée de `COMMIT_RE` : un préfixe
        court ne se récupère pas d'une forge, et deux commits pourraient le partager."""
        with pytest.raises(EventError, match=r"\$\.commit"):
            code_event_catalog().check_event(
                _event(
                    hosting_events.VERSION_ORDERED_EVENT,
                    {"workspace_id": "w1", "number": 3, "commit": "abc1234", "label": "v3"},
                )
            )

    def test_une_version_servie_ne_porte_jamais_de_refus(self) -> None:
        """L'invariant que la base tient aussi (`hosted_version_reponse_coherente`) :
        jamais les deux, jamais aucun des deux. Porter les deux laisserait l'écran choisir
        lequel croire."""
        with pytest.raises(EventError, match=r"\$\.refusal"):
            code_event_catalog().check_event(
                _event(
                    hosting_events.VERSION_SERVED_EVENT,
                    {"workspace_id": "w1", "commit": "a" * 40, "refusal": "pair_refuse"},
                )
            )

    def test_zero_device_libere_est_refuse_tant_que_le_referentiel_n_existe_pas(self) -> None:
        """La décision du ticket d'appariement : NUL, et jamais 0. Écrire 0 serait
        indiscernable, dans un an, d'un vrai « aucun device n'a été libéré » — et c'est
        précisément cette ligne qu'on viendra lire le jour où des devices ne démarrent
        plus. Ce test rougira quand le référentiel des devices arrivera : c'est le bon
        moment pour reprendre la forme, pas pour l'élargir ici."""
        revoque = {
            "public_key_fingerprint": "ab:cd",
            "environment_id": None,
            "environment_slug": None,
            "environment_label": None,
            "git_connections_destroyed": 0,
        }

        code_event_catalog().check_event(
            _event(pairing_events.PAIRING_REVOKED_EVENT, {**revoque, "devices_released": None})
        )
        with pytest.raises(EventError, match=r"\$\.devices_released"):
            code_event_catalog().check_event(
                _event(pairing_events.PAIRING_REVOKED_EVENT, {**revoque, "devices_released": 0})
            )

    def test_un_workspace_place_porte_un_identifiant_et_son_retrait_un_nul(self) -> None:
        """Ce qui rend les deux faits discernables sans interpréter l'absence d'une
        propriété : c'est la branche du producteur qui le garantit, et le schéma l'inscrit.
        """
        catalogue = code_event_catalog()

        catalogue.check_event(
            _event(
                environment_events.ENVIRONMENT_WORKSPACE_PLACED_EVENT,
                {"workspace_id": "w1", "previous_workspace_id": None},
            )
        )
        catalogue.check_event(
            _event(
                environment_events.ENVIRONMENT_WORKSPACE_CLEARED_EVENT,
                {"workspace_id": None, "previous_workspace_id": "w1"},
            )
        )
        with pytest.raises(EventError, match=r"\$\.workspace_id"):
            catalogue.check_event(
                _event(
                    environment_events.ENVIRONMENT_WORKSPACE_PLACED_EVENT,
                    {"workspace_id": None, "previous_workspace_id": "w1"},
                )
            )

    def test_une_espece_de_pair_inconnue_est_refusee(self) -> None:
        """L'énumération est DÉRIVÉE de `PeerSpecies`, qui voyage dans la chaîne signée :
        une troisième espèce déclarée là-bas entre ici toute seule."""
        with pytest.raises(EventError, match=r"\$\.species"):
            code_event_catalog().check_event(
                _event(
                    pairing_events.PAIRING_CONFIRMED_EVENT,
                    {"public_key_fingerprint": "ab:cd", "species": "terminal"},
                )
            )

    def test_une_propriete_inconnue_est_refusee_en_la_nommant(self) -> None:
        """Les blocs sont fermés : une propriété ajoutée sans être déclarée ici
        n'entrerait ni dans l'écran ni dans le contrat publié."""
        with pytest.raises(EventError, match="coquille"):
            code_event_catalog().check_event(
                _event(cultures_events.ACTIVATED_EVENT, {"count": 2, "coquille": "x"})
            )

    def test_la_cle_d_api_que_le_journal_ajoute_passe_sur_un_bloc_ferme(self) -> None:
        """Sans cette tolérance, tout event écrit par la surface MCP serait refusé pour un
        défaut sans rapport avec ce que son type déclare."""
        code_event_catalog().check_event(
            _event(cultures_events.ACTIVATED_EVENT, {"count": 2, "via_api_key": "k-1"})
        )
