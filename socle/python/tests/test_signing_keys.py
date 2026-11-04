from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from miles_socle.signing.keys import (
    SigningKeyError,
    encode_public_key,
    fingerprint,
    generate_keypair,
    load_private_key,
    parse_public_key,
)


def _pem_x25519() -> str:
    """Une clé d'un AUTRE type, engendrée ici plutôt qu'écrite en dur.

    X25519 : même famille de courbe qu'Ed25519, même forme de PEM, usage incompatible.
    Engendrée à l'exécution pour qu'aucun littéral « BEGIN PRIVATE KEY » ne dorme dans le
    dépôt — une clé en dur, même sans valeur, se lit comme un secret oublié.
    """
    return (
        X25519PrivateKey.generate()
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode("ascii")
    )


def test_une_paire_engendree_se_relit_et_les_deux_moities_vont_ensemble() -> None:
    paire = generate_keypair()

    privee = load_private_key(paire.private_pem)

    assert encode_public_key(privee.public_key()) == paire.public_key


def test_deux_appels_ne_rendent_jamais_la_meme_paire() -> None:
    # Chaque module engendre SA paire : deux environnements déployés depuis la même
    # image doivent avoir deux identités, sans quoi l'un signerait pour l'autre.
    assert generate_keypair().public_key != generate_keypair().public_key


def test_la_cle_privee_est_en_pkcs8_pem_sans_phrase_de_passe() -> None:
    # Sans phrase de passe DÉLIBÉRÉMENT : le dispositif des secrets la chiffre au repos,
    # et une phrase de passe ne ferait qu'un second secret à ranger ailleurs.
    pem = generate_keypair().private_pem

    assert pem.startswith("-----BEGIN PRIVATE KEY-----")
    assert "ENCRYPTED" not in pem


def test_la_cle_publique_tient_en_43_caracteres_sans_rembourrage() -> None:
    # Elle voyage dans une charge JSON, et un jour sous les yeux d'un humain.
    public = generate_keypair().public_key

    assert len(public) == 43
    assert "=" not in public and "\n" not in public


@pytest.mark.parametrize(
    "pem", ["", "pas du pem", "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n"]
)
def test_une_cle_privee_illisible_est_refusee(pem: str) -> None:
    with pytest.raises(SigningKeyError):
        load_private_key(pem)


def test_une_cle_privee_d_un_autre_algorithme_est_refusee() -> None:
    # Accepter la ligne reviendrait à découvrir l'erreur à la première signature.
    with pytest.raises(SigningKeyError):
        load_private_key(_pem_x25519())


def test_une_cle_privee_ne_figure_jamais_dans_le_message_de_refus() -> None:
    pem = generate_keypair().private_pem.replace("-----END", "x-----END")

    with pytest.raises(SigningKeyError) as refus:
        load_private_key(pem)

    assert pem.splitlines()[1] not in str(refus.value)


def test_une_cle_publique_se_relit_avec_ou_sans_rembourrage() -> None:
    encodee = generate_keypair().public_key

    assert encode_public_key(parse_public_key(encodee)) == encodee
    assert encode_public_key(parse_public_key(encodee + "=")) == encodee


@pytest.mark.parametrize(
    "encodee",
    [
        "",
        "pas du base64 !",
        "AAAA",  # bien du base64, mais 3 octets : pas une clé Ed25519
    ],
)
def test_une_cle_publique_invalide_est_refusee(encodee: str) -> None:
    # Entrée venue du réseau : validée avant tout usage, et refusée plutôt que tolérée.
    with pytest.raises(SigningKeyError):
        parse_public_key(encodee)


def test_trente_deux_octets_quelconques_sont_acceptes_mais_ne_verifient_rien() -> None:
    """Limite MESURÉE le 28/10/2026, pas un comportement voulu.

    `Ed25519PublicKey.from_public_bytes` n'exige que la longueur : 32 octets nuls passent,
    bien qu'ils ne soient pas un point de la courbe. Le refus se produit à la
    VÉRIFICATION, jamais à la lecture. Conséquence pour l'appariement : une clé publique
    acceptée à l'enregistrement ne prouve rien — c'est le premier appel signé qui dit si
    le pair détient la clé privée correspondante. Ce test est ici pour que la limite soit
    écrite plutôt que supposée absente.
    """
    nulle = parse_public_key("A" * 43)
    paire = generate_keypair()
    privee = load_private_key(paire.private_pem)

    with pytest.raises(InvalidSignature):
        nulle.verify(privee.sign(b"charge"), b"charge")


def test_l_empreinte_est_stable_courte_et_distingue_deux_cles() -> None:
    paire = generate_keypair()

    empreinte = fingerprint(paire.public_key)

    assert empreinte == fingerprint(paire.public_key)
    assert len(empreinte) == 32
    assert empreinte != fingerprint(generate_keypair().public_key)


def test_l_empreinte_ne_contient_pas_la_cle() -> None:
    paire = generate_keypair()

    assert paire.public_key[:16] not in fingerprint(paire.public_key)


def test_l_empreinte_ignore_le_rembourrage_comme_la_lecture() -> None:
    # Sinon deux écritures de la MÊME clé donneraient deux empreintes, et l'empreinte
    # ne servirait plus à reconnaître une clé.
    encodee = generate_keypair().public_key

    assert fingerprint(encodee) == fingerprint(encodee + "=")


def test_la_cle_publique_encodee_vient_bien_de_la_privee() -> None:
    # Garde contre un encodage qui rendrait n'importe quoi de longueur plausible.
    privee = Ed25519PrivateKey.generate()

    encodee = encode_public_key(privee.public_key())

    assert parse_public_key(encodee).public_bytes_raw() == privee.public_key().public_bytes_raw()
