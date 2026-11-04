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
from miles_socle.apikeys.presentation import key_from_headers

# Manifestement fausses : une valeur qui ressemble à une clé réelle dans un fichier
# versionné déclenche les scanners de secrets, et c'est le préfixe qui les y invite.
CLE = KEY_PREFIX + "k" * 43
AUTRE = KEY_PREFIX + "z" * 43


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


class TestLaClePresentee:
    """La règle de présentation : ce qu'on retient de ce qui a été présenté.

    Au socle depuis le 02/11/2026, deuxième usage. Ce qui est éprouvé ici n'est pas la
    lecture d'un en-tête — chaque cadre la fait à sa façon — mais le choix de NE PAS
    choisir quand deux valeurs sont présentées.
    """

    def test_le_schema_bearer_porte_la_cle(self) -> None:
        assert key_from_headers(f"Bearer {CLE}", None) == CLE
        # Casse et blancs : un client qui écrit « bearer » n'est pas en faute.
        assert key_from_headers(f"bearer   {CLE}  ", None) == CLE

    def test_l_en_tete_direct_porte_la_cle(self) -> None:
        assert key_from_headers(None, CLE) == CLE
        assert key_from_headers("", f"  {CLE} ") == CLE

    def test_les_deux_d_accord_valent_la_meme_cle(self) -> None:
        assert key_from_headers(f"Bearer {CLE}", CLE) == CLE

    def test_les_deux_en_desaccord_ne_retiennent_RIEN(self) -> None:
        """Retenir l'une laisserait l'appelant décider laquelle on vérifie — donc
        présenter une clé valide à côté d'une autre pour voir laquelle passe."""
        assert key_from_headers(f"Bearer {CLE}", AUTRE) is None

    def test_un_autre_schema_refuse_tout_meme_accompagne_d_une_cle_valable(self) -> None:
        """Un appel qui s'authentifie de deux façons dont l'une est incomprise n'est pas
        un appel dont on devine l'intention."""
        assert key_from_headers(f"Basic {CLE}", None) is None
        assert key_from_headers(f"Basic {CLE}", CLE) is None

    def test_un_bearer_sans_valeur_et_l_absence_ne_retiennent_rien(self) -> None:
        assert key_from_headers("Bearer ", None) is None
        assert key_from_headers("Bearer", None) is None
        assert key_from_headers(None, None) is None
        assert key_from_headers("   ", "   ") is None
