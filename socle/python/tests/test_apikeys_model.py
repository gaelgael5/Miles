from __future__ import annotations

from miles_socle.apikeys.model import (
    KEY_PREFIX,
    KEY_RE,
    SHOWN_LENGTH,
    key_digest,
    new_key,
    same_digest,
    shown_prefix,
)


def test_une_cle_emise_a_la_forme_que_le_verificateur_exige() -> None:
    """Sans quoi une clé valide serait refusée à l'entrée, avant même la base."""
    raw = new_key()

    assert raw.startswith(KEY_PREFIX)
    assert KEY_RE.match(raw) is not None


def test_deux_cles_emises_ne_sont_jamais_la_meme() -> None:
    assert len({new_key() for _ in range(100)}) == 100


def test_le_prefixe_affiche_est_court_et_ne_contient_pas_la_cle() -> None:
    raw = new_key()

    affiche = shown_prefix(raw)

    assert len(affiche) == SHOWN_LENGTH == 12
    # Assez pour reconnaître une clé dans une liste, très loin d'assez pour la deviner :
    # il reste 35 des 43 caractères de hasard.
    assert len(raw) - len(affiche) == 35
    assert KEY_RE.match(affiche) is None


def test_l_empreinte_fait_trente_deux_octets_et_distingue_deux_cles() -> None:
    gauche, droite = new_key(), new_key()

    assert len(key_digest(gauche)) == 32
    assert key_digest(gauche) != key_digest(droite)
    # Déterministe : c'est ce qui permet de retrouver une clé par son empreinte seule.
    assert key_digest(gauche) == key_digest(gauche)


def test_la_comparaison_reconnait_la_meme_empreinte_et_refuse_les_autres() -> None:
    raw = new_key()

    assert same_digest(key_digest(raw), key_digest(raw))
    assert not same_digest(key_digest(raw), key_digest(new_key()))
    # Une empreinte tronquée ne concorde pas : la comparaison n'est pas un préfixe.
    assert not same_digest(key_digest(raw), key_digest(raw)[:31])
