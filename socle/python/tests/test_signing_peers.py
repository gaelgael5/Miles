from __future__ import annotations

import pytest

from miles_socle.signing.identity_model import SIGNING_KEY_TYPE
from miles_socle.signing.keys import generate_keypair
from miles_socle.signing.peers import (
    IdentityInputError,
    validate_algorithm,
    validate_base_url,
    validate_public_key,
)


def test_une_cle_publique_engendree_par_le_socle_a_la_forme_attendue() -> None:
    # Les deux moitiés du dispositif doivent s'accorder : ce que ce paquet engendre doit
    # passer son propre validateur ET la contrainte de la base des trois produits. Sans ce
    # test, un changement d'encodage se découvrirait au premier démarrage sur base neuve.
    public = generate_keypair().public_key

    assert validate_public_key(public) == public


@pytest.mark.parametrize(
    "public_key",
    [
        "",
        "trop-court",
        "A" * 42,
        "A" * 44,
        "A" * 42 + "=",  # rembourré : ce n'est pas la forme stockée
        "A" * 42 + "+",  # base64 standard, pas url-safe
    ],
)
def test_une_cle_publique_mal_formee_est_refusee(public_key: str) -> None:
    with pytest.raises(IdentityInputError) as refus:
        validate_public_key(public_key)

    assert refus.value.field == "public_key"


@pytest.mark.parametrize(
    ("entree", "attendu"),
    [
        ("https://enrolement.example.org", "https://enrolement.example.org"),
        ("https://enrolement.example.org/", "https://enrolement.example.org"),
        ("  http://host-test-37:8081  ", "http://host-test-37:8081"),
    ],
)
def test_une_origine_de_pair_est_normalisee(entree: str, attendu: str) -> None:
    # Le slash final et les espaces disparaissent : l'origine stockée est comparée
    # CARACTÈRE PAR CARACTÈRE à celle déclarée dans l'en-tête d'un appel signé.
    assert validate_base_url(entree) == attendu


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "enrolement.example.org",
        "ftp://enrolement.example.org",
        "https://enrolement.example.org/chemin",
        "https://enrolement.example.org?q=1",
        "https://enrolement.example.org\nX-Injecte: 1",
        "https://" + "a" * 200,
    ],
)
def test_une_origine_de_pair_mal_formee_est_refusee(base_url: str) -> None:
    # Entrée utilisateur employée ensuite comme URL d'appel sortant : validée avant tout
    # usage, jamais concaténée sur la foi de ce qui a été saisi.
    with pytest.raises(IdentityInputError) as refus:
        validate_base_url(base_url)

    assert refus.value.field == "base_url"


def test_seul_ed25519_est_admis() -> None:
    assert validate_algorithm("ed25519") == "ed25519"
    with pytest.raises(IdentityInputError):
        validate_algorithm("rsa")


def test_le_type_du_secret_est_celui_que_le_socle_connait() -> None:
    # Le dispositif des secrets refuse tout type absent de sa liste : un type inventé ici
    # ferait échouer la création de la clé au premier démarrage, et nulle part ailleurs.
    from miles_socle.secrets.model import SECRET_TYPES

    assert SIGNING_KEY_TYPE in SECRET_TYPES
