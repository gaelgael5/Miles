from __future__ import annotations

from typing import Any

import pytest

from miles_socle.cultures import service as cultures
from miles_socle.events.catalog import EventCatalog, introduced_by
from miles_socle.events.categories import of_number
from miles_socle.events.model import EventAuthor, EventError, NewEvent, ObjectRef
from miles_socle.oidc import service as oidc
from miles_socle.pairing import events as pairing
from miles_socle.secrets import service as secrets
from miles_socle.signing import identity_model as module_identity

AUTEUR = EventAuthor("local", "admin")
MODULES = (cultures, oidc, secrets, module_identity, pairing)
# Les modules du socle sont produits par les TROIS produits : la catégorie vient du
# produit, et celle choisie ici n'a pas d'importance pour éprouver les formes.
CATALOGUE = EventCatalog(introduced_by(of_number(0), *(module.EVENT_SHAPES for module in MODULES)))


def _event(event_type: str, proprietes: dict[str, Any]) -> NewEvent:
    return NewEvent(event_type, (ObjectRef("secret", "s1"),), AUTEUR, proprietes)


class TestLesFormesDesModulesDuSocle:
    """Le socle est consommé par les trois produits : une forme fausse ici en casse trois.

    Construire `CATALOGUE` au chargement du module suffit à éprouver les refus de
    chargement — doublon, bloc qui n'est pas un objet, bloc qui redéclare un champ de la
    racine commune, schéma invalide : chacun ferait échouer la collecte de ce fichier.
    """

    def test_chaque_module_derive_ses_types_de_ses_formes(self) -> None:
        for module in MODULES:
            assert module.EVENT_TYPES == frozenset(f.name for f in module.EVENT_SHAPES), module

    def test_le_catalogue_porte_les_quatorze_types_partages(self) -> None:
        # Discriminant : un module compté deux fois ou une forme perdue change ce nombre,
        # là où l'égalité d'ensembles avec `EVENT_TYPES` serait tautologique.
        assert len(CATALOGUE.names()) == 14

    @pytest.mark.parametrize(
        ("event_type", "bloc"),
        [
            (cultures.ACTIVATED_EVENT, {"count": 3}),
            (cultures.DEACTIVATED_EVENT, {"count": 1}),
            (oidc.CREATED_EVENT, {"issuer": "https://idp.example"}),
            (oidc.UPDATED_EVENT, {"changes": {"active": {"before": False, "after": True}}}),
            (oidc.DELETED_EVENT, {}),
            (oidc.ADMIN_RECOGNIZED_EVENT, {"sub": "abc-123"}),
            (secrets.CREATED_EVENT, {"secret_type": "GIT_TOKEN"}),
            (secrets.VALUE_REPLACED_EVENT, {}),
            (secrets.RELABELED_EVENT, {"label": "Jeton de la forge"}),
            (secrets.DELETED_EVENT, {"secret_type": "GIT_TOKEN"}),
            (module_identity.IDENTITY_CREATED_EVENT, {"public_key_fingerprint": "ab:cd:ef"}),
            (
                pairing.PAIRING_REQUESTED_EVENT,
                {
                    "base_url": "https://enrolement.example",
                    "declared_name": "env-de-recette",
                    "species": "environnement",
                    "public_key_fingerprint": "ab:cd",
                },
            ),
            (
                pairing.PEER_REGISTERED_EVENT,
                {
                    "base_url": "https://enrolement.example",
                    "public_key_fingerprint": "ab:cd",
                    "contact_url": "https://enrolement.example",
                },
            ),
            (pairing.PAIRING_CANCELLED_EVENT, {}),
        ],
    )
    def test_ce_que_le_producteur_ecrit_passe(self, event_type: str, bloc: dict[str, Any]) -> None:
        """Les quatorze blocs, pris sur leurs producteurs le 12/11/2026. Ce ne sont pas
        des exemples : c'est ce que le code écrit, et un écart ferait refuser un geste
        réel."""
        CATALOGUE.check_event(_event(event_type, bloc))

    def test_un_changement_oidc_dit_toujours_son_avant_et_son_apres(self) -> None:
        """Les deux cases, parce que deux des champs suivis sont des réglages de sécurité :
        un journal qui ne dit pas ce qu'il y avait avant ne dit pas qui a décoché."""
        with pytest.raises(EventError, match=r"\$\.changes\.active"):
            CATALOGUE.check_event(
                _event(oidc.UPDATED_EVENT, {"changes": {"active": {"after": True}}})
            )

    def test_aucune_valeur_de_secret_ne_peut_entrer_dans_le_journal(self) -> None:
        """Le refus porte la règle : jamais la valeur, ni chiffrée ni tronquée — le journal
        est lu bien plus largement que la table des secrets. Le bloc est fermé, donc une
        propriété ajoutée sans être déclarée ici ne passe pas."""
        with pytest.raises(EventError, match="value"):
            CATALOGUE.check_event(
                _event(secrets.CREATED_EVENT, {"secret_type": "GIT_TOKEN", "value": "s3cret"})
            )
        # Même refus sans le type : il est alors nommé le premier, parce qu'une propriété
        # obligatoire absente se lit avant une propriété de trop. Le bloc est refusé dans
        # les deux cas, et c'est ce qui compte ici.
        with pytest.raises(EventError):
            CATALOGUE.check_event(_event(secrets.CREATED_EVENT, {"value": "s3cret"}))

    def test_un_compte_de_cultures_nul_est_refuse(self) -> None:
        """Un rejeu n'écrit rien : l'event n'existe que s'il a changé quelque chose, et
        `count: 0` serait la trace d'un geste qui n'a rien fait."""
        with pytest.raises(EventError, match=r"\$\.count"):
            CATALOGUE.check_event(_event(cultures.ACTIVATED_EVENT, {"count": 0}))

    def test_l_adresse_d_identite_et_celle_de_contact_sont_toutes_deux_exigees(self) -> None:
        """Les confondre est l'erreur que le ticket ba44914b corrige : `base_url` est
        l'identité du pair, `contact_url` l'adresse où on le joint. Un event qui n'en
        porterait qu'une ferait chercher « où croyait-on l'appeler ? » sans réponse."""
        with pytest.raises(EventError, match="contact_url"):
            CATALOGUE.check_event(
                _event(
                    pairing.PEER_REGISTERED_EVENT,
                    {"base_url": "https://e.example", "public_key_fingerprint": "ab:cd"},
                )
            )
