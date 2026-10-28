from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.events.model import LOCAL_DIRECTORY, EventAuthor
from miles_socle.signing.keys import fingerprint

from environnement.identity.model import (
    PairingAttemptMissingError,
    PairingRefusedByPeerError,
    PeerClockSkewError,
)
from environnement.identity.service import PAIRING_REQUESTED_EVENT, PEER_REGISTERED_EVENT
from tests.integration.environnement_stack import PUBLIC_URL, open_stack
from tests.integration.peer_double import EXPECTED_CODE, PEER_ORIGIN, EnrolmentDouble

pytestmark = pytest.mark.integration

# L'auteur qu'un appel d'administration porterait : ces deux tests passent par le
# service, donc sans requête HTTP pour le déduire.
AUTEUR = EventAuthor(LOCAL_DIRECTORY, "miles-admin")


async def test_frapper_depose_notre_cle_publique_et_ouvre_une_demande(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        reponse = await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        assert reponse.status_code == 202, reponse.text
        assert reponse.json()["base_url"] == PEER_ORIGIN
        # Le pair a bien reçu NOTRE clé publique, et il l'a reçue signée par elle : sa
        # doublure appelle le vérificateur du socle, pas une complaisance.
        identite = await stack.client.get("/api/identity")
        assert double.expects_public_key == identite.json()["public_key"]
        assert double.received == [PUBLIC_URL]
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type = $1", PAIRING_REQUESTED_EVENT
            )
            == 1
        )


async def test_aucune_cle_privee_ne_part_sur_le_reseau(blank_db: str, tmp_path: Path) -> None:
    """Interdit central du ticket, éprouvé sur les OCTETS réellement envoyés."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})

    assert double.bodies, "la contrepartie n'a rien reçu : le test ne prouverait rien"
    for corps in double.bodies:
        assert b"PRIVATE" not in corps.upper()
        assert b"BEGIN" not in corps.upper()


async def test_le_code_accepte_range_la_cle_du_pair_et_referme_la_demande(
    blank_db: str, tmp_path: Path
) -> None:
    """Le cas nominal côté environnement : à l'issue, chacun a la clé publique de l'autre."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        reponse = await stack.client.post(
            "/api/identity/pairing/confirm", json={"code": EXPECTED_CODE}
        )

        assert reponse.status_code == 200, reponse.text
        assert reponse.json()["base_url"] == PEER_ORIGIN
        assert reponse.json()["public_key"] == double.keypair.public_key
        assert reponse.json()["public_key_fingerprint"] == fingerprint(double.keypair.public_key)
        # La demande est refermée : elle n'a plus de destinataire à désigner.
        assert (await stack.client.get("/api/identity/pairing")).status_code == 404
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type = $1", PEER_REGISTERED_EVENT
            )
            == 1
        )


async def test_une_fois_apparie_l_appel_signe_vers_le_pair_passe(
    blank_db: str, tmp_path: Path
) -> None:
    """La preuve que les clés déposées de part et d'autre servent réellement."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})

        pong = await stack.client.post("/api/identity/peer/ping")

        assert pong.status_code == 200, pong.text
        identite = await stack.client.get("/api/identity")
        assert pong.json()["verified_key_fingerprint"] == identite.json()["public_key_fingerprint"]


async def test_un_code_refuse_par_le_pair_ne_range_aucune_cle(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        reponse = await stack.client.post("/api/identity/pairing/confirm", json={"code": "000000"})

        assert reponse.status_code == 409
        assert reponse.json()["detail"] == "appariement_refuse"
        assert await stack.pool.fetchval("SELECT count(*) FROM enrolment_peer") == 0
        # La demande SURVIT : le pair a gardé la sienne, et l'humain doit pouvoir
        # recommencer avec le code suivant sans tout reprendre.
        assert (await stack.client.get("/api/identity/pairing")).status_code == 200


async def test_la_derive_d_horloge_annoncee_par_le_pair_est_rendue_telle_quelle(
    blank_db: str, tmp_path: Path
) -> None:
    """Le seul refus que le pair détaille, et ce module ne doit pas l'aplatir.

    Sans lui, l'administrateur chercherait du côté du code pendant que la cause est une
    machine à l'heure près.
    """
    double = EnrolmentDouble(
        confirm_status=409,
        confirm_payload={"detail": "horloges_desynchronisees", "drift_s": -150},
    )
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        reponse = await stack.client.post(
            "/api/identity/pairing/confirm", json={"code": EXPECTED_CODE}
        )

        assert reponse.status_code == 409
        assert reponse.json() == {"detail": "horloges_desynchronisees", "drift_s": -150}


async def test_une_derive_invraisemblable_annoncee_par_le_pair_retombe_sur_le_refus(
    blank_db: str, tmp_path: Path
) -> None:
    """Ce nombre vient d'un AUTRE service et finira sur un écran : il est borné.

    Hors bornes, on ne le recopie pas et on ne l'invente pas non plus — on retombe sur le
    refus générique, qui est vrai.
    """
    double = EnrolmentDouble(
        confirm_status=409,
        confirm_payload={"detail": "horloges_desynchronisees", "drift_s": 10**12},
    )
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        reponse = await stack.client.post(
            "/api/identity/pairing/confirm", json={"code": EXPECTED_CODE}
        )

        assert reponse.status_code == 409
        assert reponse.json()["detail"] == "appariement_refuse"


async def test_une_reponse_inattendue_du_pair_n_est_ni_un_refus_ni_une_panne_reseau(
    blank_db: str, tmp_path: Path
) -> None:
    # Un 500 chez lui ne doit pas faire réapparier pour rien, ni envoyer chercher un
    # problème de réseau là où il n'y en a pas.
    double = EnrolmentDouble(confirm_status=500)
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        reponse = await stack.client.post(
            "/api/identity/pairing/confirm", json={"code": EXPECTED_CODE}
        )

        assert reponse.status_code == 502
        assert reponse.json()["detail"] == "reponse_inattendue_du_pair"
        assert reponse.json()["peer_status"] == 500


async def test_sans_demande_en_cours_un_code_n_a_pas_de_destinataire(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        reponse = await stack.client.post(
            "/api/identity/pairing/confirm", json={"code": EXPECTED_CODE}
        )

        assert reponse.status_code == 404
        assert reponse.json()["detail"] == "aucune_demande"


async def test_la_demande_survit_a_un_redemarrage_du_module(blank_db: str, tmp_path: Path) -> None:
    """Critère 6 vu de ce côté : l'état n'est pas en mémoire de processus.

    L'appariement se fait en deux gestes séparés par un aller-retour humain. Entre les
    deux, le processus peut redémarrer et l'écran être rouvert ailleurs.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

    # Second montage sur la MÊME base : un autre processus, au sens de ce qui compte ici.
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        en_cours = await stack.client.get("/api/identity/pairing")

        assert en_cours.status_code == 200
        assert en_cours.json()["base_url"] == PEER_ORIGIN


async def test_frapper_ailleurs_abandonne_la_demande_precedente(
    blank_db: str, tmp_path: Path
) -> None:
    # Un environnement n'a qu'un module d'enrôlement : garder deux demandes laisserait
    # l'humain coller un code sans savoir chez qui il part.
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": "http://autre-enrolement.test"}
        )

        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_attempt") == 1
        en_cours = await stack.client.get("/api/identity/pairing")
        assert en_cours.json()["base_url"] == "http://autre-enrolement.test"


async def test_annuler_referme_la_demande(blank_db: str, tmp_path: Path) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        assert (await stack.client.delete("/api/identity/pairing")).status_code == 204
        assert (await stack.client.get("/api/identity/pairing")).status_code == 404
        # Annuler deux fois n'est pas une erreur de serveur : c'est un 404 lisible.
        assert (await stack.client.delete("/api/identity/pairing")).status_code == 404


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", "12 345"])
async def test_un_code_mal_forme_est_refuse_avant_de_partir_sur_le_reseau(
    blank_db: str, tmp_path: Path, code: str
) -> None:
    """La saisie est la NÔTRE : la valider ici, et non la faire valider par le pair."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})
        envois = len(double.bodies)

        reponse = await stack.client.post("/api/identity/pairing/confirm", json={"code": code})

        assert reponse.status_code == 422
        assert reponse.json()["detail"] == "code"
        assert len(double.bodies) == envois


@pytest.mark.parametrize(
    "base_url",
    ["", "enrolement.test", "ftp://enrolement.test", "http://enrolement.test/chemin"],
)
async def test_une_origine_mal_formee_est_refusee_avant_tout_appel(
    blank_db: str, tmp_path: Path, base_url: str
) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        reponse = await stack.client.post("/api/identity/pairing", json={"base_url": base_url})

        assert reponse.status_code == 422
        assert reponse.json()["detail"] == "base_url"
        assert double.bodies == []


async def test_le_reappariement_remplace_le_pair_sans_le_doubler(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 13 : un seul appariement par environnement, garanti par le MODÈLE."""
    premier = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=premier.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
        creation = await stack.pool.fetchval("SELECT created_at FROM enrolment_peer")

    second = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=second.app()) as stack:
        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})

        lignes = await stack.pool.fetch("SELECT public_key, created_at FROM enrolment_peer")
        assert len(lignes) == 1
        assert lignes[0]["public_key"] == second.keypair.public_key
        assert lignes[0]["created_at"] == creation


async def test_l_identite_du_module_ne_change_pas_au_reappariement(
    blank_db: str, tmp_path: Path
) -> None:
    """Interdit du ticket : jamais de régénération. Elle casserait tous les appariements."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        avant = (await stack.client.get("/api/identity")).json()

        await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})

        apres = (await stack.client.get("/api/identity")).json()
        assert apres["public_key"] == avant["public_key"]
        assert apres["created_at"] == avant["created_at"]


async def test_les_routes_d_appariement_exigent_une_session(blank_db: str, tmp_path: Path) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        async with stack.anonymous() as visiteur:
            lecture = await visiteur.get("/api/identity/pairing")
            ecriture = await visiteur.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN})

        assert lecture.status_code == 401
        assert lecture.json()["detail"] == "session_requise"
        assert ecriture.status_code == 401
        assert double.bodies == []


async def test_les_erreurs_du_service_portent_leur_cause(blank_db: str, tmp_path: Path) -> None:
    """Les trois refus que le service lève, vus depuis le service lui-même.

    Les routes les traduisent en statuts ; ce test dit que ce sont bien ces exceptions-là
    qui sortent, de sorte qu'un renommage ne puisse pas les faire retomber dans le repli
    générique sans que rien ne rougisse.
    """
    double = EnrolmentDouble(confirm_status=401)
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        with pytest.raises(PairingAttemptMissingError):
            await stack.identity.resolve_attempt()

        await stack.identity.resolve_request_pairing(AUTEUR, PEER_ORIGIN)
        with pytest.raises(PairingRefusedByPeerError):
            await stack.identity.resolve_confirm_pairing(AUTEUR, EXPECTED_CODE)

        double.confirm_status = 409
        double.confirm_payload = {"detail": "horloges_desynchronisees", "drift_s": 90}
        with pytest.raises(PeerClockSkewError) as derive:
            await stack.identity.resolve_confirm_pairing(AUTEUR, EXPECTED_CODE)
        assert derive.value.drift_s == 90
