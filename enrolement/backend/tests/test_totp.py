from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from enrolement.pairing.totp import (
    ACCEPTED_OFFSETS,
    DIGITS,
    DRIFT_SEARCH_WINDOWS,
    STEP_S,
    new_totp_secret,
    resolve_code_offset,
    seconds_remaining,
    totp_code,
)

# Un instant FIGÉ, et au milieu d'une fenêtre : un instant pris de l'horloge ferait
# basculer le test une fois sur trente, à la seconde près où la fenêtre change.
INSTANT = datetime(2026, 10, 28, 12, 0, 15, tzinfo=UTC)


def test_un_code_a_la_longueur_attendue_et_ne_contient_que_des_chiffres() -> None:
    code = totp_code(new_totp_secret(), INSTANT)

    assert len(code) == DIGITS
    assert code.isdigit()


def test_deux_secrets_distincts_ne_donnent_pas_le_meme_code() -> None:
    # Valeurs DISCRIMINANTES : si les deux codes pouvaient coïncider par construction, le
    # test resterait vert alors que le secret n'entrerait pas dans le calcul.
    premier, second = new_totp_secret(), new_totp_secret()

    assert totp_code(premier, INSTANT) != totp_code(second, INSTANT)


def test_le_code_change_de_fenetre_en_fenetre() -> None:
    secret = new_totp_secret()

    assert totp_code(secret, INSTANT) != totp_code(secret, INSTANT + timedelta(seconds=STEP_S))


def test_le_code_ne_change_pas_a_l_interieur_d_une_fenetre() -> None:
    secret = new_totp_secret()
    debut = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    assert totp_code(secret, debut) == totp_code(secret, debut + timedelta(seconds=STEP_S - 1))


@pytest.mark.parametrize("offset", ACCEPTED_OFFSETS)
def test_la_fenetre_courante_et_la_precedente_sont_reconnues(offset: int) -> None:
    secret = new_totp_secret()
    code = totp_code(secret, INSTANT + timedelta(seconds=offset * STEP_S))

    assert resolve_code_offset(secret, code, INSTANT) == offset


def test_une_fenetre_plus_ancienne_est_reconnue_mais_pas_acceptee() -> None:
    # C'est ce qui permet de NOMMER l'horloge : le code est bon, il est seulement trop
    # vieux. Sans ce décalage rendu, le message ne pourrait pas faire la différence avec
    # un code faux, et le diagnostic partirait sur le code.
    secret = new_totp_secret()
    code = totp_code(secret, INSTANT - timedelta(seconds=5 * STEP_S))

    decalage = resolve_code_offset(secret, code, INSTANT)

    assert decalage == -5
    assert decalage not in ACCEPTED_OFFSETS


def test_une_derive_hors_de_portee_de_recherche_est_indiscernable_d_un_code_faux() -> None:
    secret = new_totp_secret()
    trop_loin = DRIFT_SEARCH_WINDOWS + 1
    code = totp_code(secret, INSTANT - timedelta(seconds=trop_loin * STEP_S))

    assert resolve_code_offset(secret, code, INSTANT) is None


def test_le_code_d_un_autre_secret_n_est_jamais_reconnu() -> None:
    # Le cas qui compte : deux demandes en attente simultanées, et le code de l'une ne
    # doit pas valoir pour l'autre.
    code = totp_code(new_totp_secret(), INSTANT)

    assert resolve_code_offset(new_totp_secret(), code, INSTANT) is None


@pytest.mark.parametrize("code", ["", "12345", "1234567", "12345a", "   123", "abcdef"])
def test_une_saisie_qui_n_a_pas_la_forme_d_un_code_est_refusee(code: str) -> None:
    # Avant tout calcul : une saisie malformée ne doit pas entrer dans la comparaison, et
    # surtout pas y entrer quarante et une fois.
    assert resolve_code_offset(new_totp_secret(), code, INSTANT) is None


def test_le_temps_restant_est_celui_de_la_fenetre_courante() -> None:
    debut = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)

    assert seconds_remaining(debut) == STEP_S
    assert seconds_remaining(debut + timedelta(seconds=1)) == STEP_S - 1
    assert seconds_remaining(debut + timedelta(seconds=STEP_S - 1)) == 1


def test_deux_secrets_engendres_ne_sont_jamais_les_memes() -> None:
    # Un secret par demande : s'il était constant, le code d'une demande vaudrait pour
    # toutes, et le premier environnement admis les admettrait tous.
    assert len({new_totp_secret() for _ in range(20)}) == 20
