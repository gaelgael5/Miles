from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from miles_socle.signing.calls import (
    MAX_ORIGIN_LENGTH,
    VERSION,
    CallSignatureError,
    canonical_bytes,
    origin_for_log,
    sign_call,
    validate_origin,
    verify_call,
)
from miles_socle.signing.keys import generate_keypair, load_private_key, parse_public_key

ORIGINE = "https://env-essai.example.org"
METHODE = "POST"
CIBLE = "/api/peer/ping"
CORPS = b'{"nonce":"abc"}'


def _paire() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    paire = generate_keypair()
    return load_private_key(paire.private_pem), parse_public_key(paire.public_key)


def _signe(privee: Ed25519PrivateKey, origine: str = ORIGINE) -> str:
    return sign_call(privee, origin=origine, method=METHODE, target=CIBLE, body=CORPS)


def _verifie(
    publique: Ed25519PublicKey,
    entete: str | None,
    *,
    origin: str = ORIGINE,
    method: str = METHODE,
    target: str = CIBLE,
    body: bytes = CORPS,
) -> None:
    verify_call(publique, entete, origin=origin, method=method, target=target, body=body)


def test_un_appel_signe_est_verifie_par_la_cle_publique_du_signataire() -> None:
    privee, publique = _paire()

    _verifie(publique, _signe(privee))


def test_un_appel_signe_par_une_autre_cle_est_refuse() -> None:
    # Le cas qui compte : une clé INCONNUE. C'est tout ce qui sépare un pair apparié de
    # quiconque connaît l'URL du module.
    privee, _ = _paire()
    _, publique_d_un_autre = _paire()

    with pytest.raises(CallSignatureError) as refus:
        _verifie(publique_d_un_autre, _signe(privee))

    assert refus.value.reason == "signature_invalide"


def test_une_autre_methode_invalide_la_signature() -> None:
    privee, publique = _paire()

    with pytest.raises(CallSignatureError) as refus:
        _verifie(publique, _signe(privee), method="GET")

    assert refus.value.reason == "signature_invalide"


def test_une_autre_cible_invalide_la_signature() -> None:
    # Une signature rejouée vers une AUTRE route du même module est refusée.
    privee, publique = _paire()

    with pytest.raises(CallSignatureError):
        _verifie(publique, _signe(privee), target="/api/peer/autre-chose")


def test_un_corps_modifie_invalide_la_signature() -> None:
    # La signature lie le CONTENU : un relais qui altère la charge est détecté.
    privee, publique = _paire()

    with pytest.raises(CallSignatureError):
        _verifie(publique, _signe(privee), body=b'{"nonce":"abd"}')


def test_changer_l_origine_declaree_invalide_la_signature() -> None:
    # L'origine entre dans ce qui est signé : sans cela, le champ que le journal nomme
    # serait modifiable par un relais, et le journal ne prouverait plus rien.
    privee, publique = _paire()

    with pytest.raises(CallSignatureError):
        _verifie(publique, _signe(privee), origin="https://ailleurs.example.org")


@pytest.mark.parametrize("entete", [None, ""])
def test_un_appel_sans_en_tete_de_signature_est_refuse(entete: str | None) -> None:
    # Fail closed : l'absence de signature est un refus, jamais un passe-droit.
    _, publique = _paire()

    with pytest.raises(CallSignatureError) as refus:
        _verifie(publique, entete)

    assert refus.value.reason == "absente"


@pytest.mark.parametrize(
    ("entete", "raison"),
    [
        ("v1", "forme_invalide"),
        ("YWJj", "forme_invalide"),
        ("v1 aaa bbb", "forme_invalide"),
        ("v1 pas-du-base64-!!", "forme_invalide"),
        ("v2 YWJj", "version_inconnue"),
    ],
)
def test_une_en_tete_mal_formee_est_refusee_sans_toucher_a_la_cryptographie(
    entete: str, raison: str
) -> None:
    _, publique = _paire()

    with pytest.raises(CallSignatureError) as refus:
        _verifie(publique, entete)

    assert refus.value.reason == raison


def test_une_signature_de_la_bonne_forme_mais_du_mauvais_contenu_est_refusee() -> None:
    _, publique = _paire()

    with pytest.raises(CallSignatureError) as refus:
        _verifie(publique, f"{VERSION} {'A' * 86}")

    assert refus.value.reason == "signature_invalide"


def test_la_chaine_canonique_porte_la_version_et_l_empreinte_du_corps() -> None:
    champs = canonical_bytes(method=METHODE, target=CIBLE, origin=ORIGINE, body=CORPS)
    canonique = champs.decode("utf-8").split("\n")

    assert canonique[0] == f"miles-call-{VERSION}"
    assert canonique[1:4] == [METHODE, CIBLE, ORIGINE]
    # Le corps entre par son empreinte, pas en entier : une charge de plusieurs
    # mégaoctets n'a pas à être recopiée en mémoire pour être signée.
    assert len(canonique[4]) == 64
    assert CORPS.decode() not in champs.decode("utf-8")


def test_la_methode_est_normalisee_en_majuscules() -> None:
    # Un client qui signe « post » et un serveur qui vérifie « POST » doivent s'entendre.
    privee, publique = _paire()
    entete = sign_call(privee, origin=ORIGINE, method="post", target=CIBLE, body=CORPS)

    _verifie(publique, entete)


def test_un_corps_vide_se_signe_aussi() -> None:
    privee, publique = _paire()
    entete = sign_call(privee, origin=ORIGINE, method="GET", target=CIBLE, body=b"")

    _verifie(publique, entete, method="GET", body=b"")


@pytest.mark.parametrize(
    "origine",
    [
        "",
        "env.example.org",
        "ftp://env.example.org",
        "https://env.example.org/chemin",
        "https://env.example.org\nX-Injecte: 1",
        "https://" + "a" * MAX_ORIGIN_LENGTH,
    ],
)
def test_une_origine_mal_formee_est_refusee(origine: str) -> None:
    # Dont le retour à la ligne : il porterait le séparateur de la chaîne canonique et
    # permettrait de déplacer la frontière entre deux champs signés.
    with pytest.raises(CallSignatureError) as refus:
        validate_origin(origine)

    assert refus.value.reason == "origine_invalide"


def test_on_ne_signe_pas_pour_une_origine_mal_formee() -> None:
    privee, _ = _paire()

    with pytest.raises(CallSignatureError):
        _signe(privee, origine="https://env.example.org/chemin")


@pytest.mark.parametrize(
    ("declaree", "journalisee"),
    [
        (ORIGINE, ORIGINE),
        ("http://env.example.org:8082", "http://env.example.org:8082"),
        (None, "(absente)"),
        ("", "(absente)"),
        ("https://env.example.org\nniveau=critique", "(origine_invalide)"),
        ("x" * 500, "(origine_invalide)"),
    ],
)
def test_l_origine_journalisee_est_validee_avant_d_etre_ecrite(
    declaree: str | None, journalisee: str
) -> None:
    # Le journal doit nommer l'origine d'un appel refusé — c'est tout ce qu'on a pour
    # retrouver qui frappe. Mais avant vérification, cette origine est une entrée
    # ANONYME : la recopier telle quelle écrirait dans nos journaux ce qu'un inconnu y met.
    assert origin_for_log(declaree) == journalisee
