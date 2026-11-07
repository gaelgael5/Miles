"""Le drainage du corps avant un refus, au point d'entrée du mode gros fichier.

Ce qui s'éprouve ici est la BORNE du geste, et non son effet sur le mandataire : le 502
qu'il répare ne se voit que derrière nginx, et aucun test ne monte le proxy (bug
`abc1b595`). La vérification de bout en bout est donc faite sur la machine de test, par le
port publié ; ce fichier tient ce qu'une doublure peut dire — qu'on consomme le reste, et
qu'on s'arrête avant d'absorber un document entier déjà refusé.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from starlette.requests import ClientDisconnect

from environnement.ingestion.api_ingest_file import DRAIN_MAX, _drain

BLOC = 4 * 1024 * 1024


async def test_le_drainage_s_arrete_a_sa_borne_plutot_que_d_absorber_tout_le_document() -> None:
    """Sans borne, une clé refusée donnerait le pouvoir de nous faire lire deux gigaoctets.

    Dix blocs offerts, et le drainage doit s'arrêter dès que la borne est dépassée : trois
    blocs de quatre mégaoctets pour une borne de huit, parce que c'est le bloc qui FRANCHIT
    la borne qui décide — on ne peut pas s'arrêter avant de l'avoir lu.
    """
    produits: list[int] = []

    async def flux() -> AsyncIterator[bytes]:
        for _ in range(10):
            produits.append(BLOC)
            yield b"x" * BLOC

    await _drain(flux())

    assert sum(produits) > DRAIN_MAX
    assert len(produits) == 3


async def test_un_corps_court_est_draine_EN_ENTIER_pour_que_le_refus_arrive_lisible() -> None:
    """Le cas qui compte vraiment : le partenaire qui se trompe de clé.

    Son document tient sous la borne, il doit donc être consommé jusqu'au bout — c'est ce
    qui permet au refus de lui parvenir au lieu d'un `502` du mandataire.
    """
    restants = [b"un", b"deux", b"trois"]

    async def flux() -> AsyncIterator[bytes]:
        while restants:
            yield restants.pop(0)

    await _drain(flux())

    assert restants == []


async def test_un_client_qui_a_raccroche_n_est_pas_une_panne() -> None:
    """`ClientDisconnect` est une fin NORMALE du drainage.

    La laisser remonter ferait journaliser une erreur là où il n'y a rien à faire : le
    refus est déjà décidé, et il n'y a plus personne pour le lire.
    """

    async def flux() -> AsyncIterator[bytes]:
        yield b"debut"
        raise ClientDisconnect

    await _drain(flux())
