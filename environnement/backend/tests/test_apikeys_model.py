from __future__ import annotations

import pytest
from miles_socle.apikeys.model import new_key

from environnement.apikeys.model import (
    MAX_LABEL,
    KeyInputError,
    KeyPrincipal,
    checked_label,
    presented_key,
)


class TestCeQuUneCleOuvre:
    def test_une_cle_ecrit_sur_les_sources_octroyees_et_sur_aucune_autre(self) -> None:
        cle = KeyPrincipal("k", "Transporteur", ("comptes-pudo",))

        assert cle.can_write("comptes-pudo")
        assert not cle.can_write("sites-pudo")

    def test_une_cle_sans_octroi_n_ouvre_rien(self) -> None:
        """Fail closed : l'absence d'octroi n'est pas un « tout ouvert » par défaut."""
        assert not KeyPrincipal("k", "Vide", ()).can_write("comptes-pudo")


class TestLeLibelle:
    def test_un_libelle_est_debarrasse_de_ses_blancs(self) -> None:
        assert checked_label("  Transporteur  ") == "Transporteur"

    def test_un_libelle_vide_ou_blanc_est_refuse_en_nommant_le_champ(self) -> None:
        with pytest.raises(KeyInputError) as refus:
            checked_label("   ")

        assert (refus.value.field, refus.value.reason) == ("label", "vide")

    def test_un_caractere_de_controle_est_refuse(self) -> None:
        """Le libellé s'affiche dans le journal : un retour à la ligne y ferait passer
        une ligne pour une autre."""
        with pytest.raises(KeyInputError):
            checked_label("Transporteur\nADMIN")

    def test_un_libelle_trop_long_est_refuse(self) -> None:
        assert checked_label("a" * MAX_LABEL) == "a" * MAX_LABEL
        with pytest.raises(KeyInputError):
            checked_label("a" * (MAX_LABEL + 1))


class TestLaClePresentee:
    def test_une_cle_bien_formee_passe(self) -> None:
        raw = new_key()

        assert presented_key(raw) == raw

    def test_une_absence_ou_une_forme_etrangere_ne_touche_pas_la_base(self) -> None:
        """Vérifié AVANT toute requête : une chaîne quelconque ne doit pas faire chercher
        une empreinte, ce que la durée de la réponse finirait par dire."""
        assert presented_key(None) is None
        assert presented_key("") is None
        assert presented_key("Bearer " + new_key()) is None
        # Le bon préfixe ne suffit pas : la longueur du hasard est dans la forme.
        assert presented_key("mlk_trop-court") is None
        # Le préfixe affiché, qui est public, n'est pas une clé.
        assert presented_key(new_key()[:12]) is None
