from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from miles_socle.events.model import LOCAL_DIRECTORY, EventAuthor
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, sign_call
from miles_socle.signing.keys import fingerprint, generate_keypair, load_private_key
from miles_socle.signing.protocol import PEER_PING_PATH

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
# Valeur neutre : aucun nom de royaume SSO, de dépôt réel ni de vocabulaire métier.
NOM = "Environnement de recette"


async def test_frapper_depose_notre_cle_publique_et_ouvre_une_demande(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        reponse = await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": "http://autre-enrolement.test", "name": NOM}
        )

        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_attempt") == 1
        en_cours = await stack.client.get("/api/identity/pairing")
        assert en_cours.json()["base_url"] == "http://autre-enrolement.test"


async def test_annuler_referme_la_demande(blank_db: str, tmp_path: Path) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

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
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
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
        reponse = await stack.client.post(
            "/api/identity/pairing", json={"base_url": base_url, "name": NOM}
        )

        assert reponse.status_code == 422
        assert reponse.json()["detail"] == "base_url"
        assert double.bodies == []


async def test_le_reappariement_remplace_le_pair_sans_le_doubler(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 13 : un seul appariement par environnement, garanti par le MODÈLE."""
    premier = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=premier.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
        creation = await stack.pool.fetchval("SELECT created_at FROM enrolment_peer")

    second = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=second.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
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

        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})

        apres = (await stack.client.get("/api/identity")).json()
        assert apres["public_key"] == avant["public_key"]
        assert apres["created_at"] == avant["created_at"]


async def test_les_routes_d_appariement_exigent_une_session(blank_db: str, tmp_path: Path) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        async with stack.anonymous() as visiteur:
            lecture = await visiteur.get("/api/identity/pairing")
            ecriture = await visiteur.post(
                "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
            )

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

        await stack.identity.resolve_request_pairing(AUTEUR, PEER_ORIGIN, NOM)
        with pytest.raises(PairingRefusedByPeerError):
            await stack.identity.resolve_confirm_pairing(AUTEUR, EXPECTED_CODE)

        double.confirm_status = 409
        double.confirm_payload = {"detail": "horloges_desynchronisees", "drift_s": 90}
        with pytest.raises(PeerClockSkewError) as derive:
            await stack.identity.resolve_confirm_pairing(AUTEUR, EXPECTED_CODE)
        assert derive.value.drift_s == 90


async def test_le_nom_declare_part_reellement_chez_le_pair(blank_db: str, tmp_path: Path) -> None:
    # Lu dans ce que la contrepartie a REÇU, pas dans ce que l'écran croit avoir envoyé.
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": "  Recette nord  "}
        )

        # Les espaces de bord disparaissent : le nom arrive d'un formulaire.
        assert double.received_names == ["Recette nord"]
        etat = await stack.client.get("/api/identity/pairing/state")
        assert etat.json()["attempt"]["name"] == "Recette nord"


@pytest.mark.parametrize(
    "nom",
    [
        "",
        "   ",
        "A" * 81,
        "deux\nlignes",
        "tabulation\tinterdite",
    ],
)
async def test_un_nom_declare_inacceptable_est_refuse_avant_tout_appel(
    blank_db: str, tmp_path: Path, nom: str
) -> None:
    """Un nom vide, démesuré ou porteur de caractères de contrôle ne part pas.

    Le retour à la ligne casse une ligne de journal structuré : il est refusé à l'entrée,
    des deux côtés, plutôt que nettoyé à l'affichage où on l'oublierait.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        reponse = await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": nom}
        )

        assert reponse.status_code == 422
        assert reponse.json()["detail"] == "name"
        assert double.bodies == []


async def test_un_nom_qui_ressemble_a_du_balisage_passe_tel_quel(
    blank_db: str, tmp_path: Path
) -> None:
    """Délibéré : l'échappement appartient à l'AFFICHAGE, qui sait dans quel contexte il écrit.

    Le mutiler ici abîmerait un nom légitime tout en donnant l'illusion d'une protection —
    et le jour où un écran oublierait d'échapper, personne ne le verrait.
    """
    hostile = '<script>alert(1)</script> & "guillemets"'
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        reponse = await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": hostile}
        )

        assert reponse.status_code == 202
        assert double.received_names == [hostile]


async def test_sans_appariement_ni_demande_l_etat_le_dit(blank_db: str, tmp_path: Path) -> None:
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json() == {"state": "non_apparie", "attempt": None, "peer": None}


async def test_les_quatre_etats_que_l_administrateur_peut_rencontrer(
    blank_db: str, tmp_path: Path
) -> None:
    """Non apparié, en attente, refusée, appariée — et jamais l'une prise pour l'autre.

    Un écran qui ne distingue pas « en attente » d'« échoué » fait recommencer la demande
    indéfiniment, ou fait attendre une acceptation qui ne viendra jamais.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:

        async def etat() -> dict[str, object]:
            reponse = await stack.client.get("/api/identity/pairing/state")
            assert reponse.status_code == 200, reponse.text
            return dict(reponse.json())

        assert (await etat())["state"] == "non_apparie"

        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        assert (await etat())["state"] == "en_attente"

        # Le pair ne dit que « inconnue ». C'est l'échéance, qu'il nous a annoncée en
        # accusant la demande, qui tranche : encore à venir, un humain a donc refusé.
        double.status_state = "inconnue"
        assert (await etat())["state"] == "refusee"

        double.status_state = "en_attente"
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
        apparie = await etat()
        assert apparie["state"] == "apparie"
        assert apparie["attempt"] is None
        assert apparie["peer"] is not None


async def test_une_demande_dont_l_echeance_est_passee_est_dite_expiree(
    blank_db: str, tmp_path: Path
) -> None:
    # Même réponse du pair — « inconnue » — et pourtant l'autre verdict : seule l'échéance
    # les sépare, et c'est nous qui la détenons.
    double = EnrolmentDouble(expires_at="2020-01-01T00:00:00+00:00")
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        double.status_state = "inconnue"

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "expiree"


async def test_un_pair_injoignable_n_est_pas_un_refus(blank_db: str, tmp_path: Path) -> None:
    """Faire recommencer la demande pour une panne de réseau détruirait un appariement en cours."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        # Un 500 : il a répondu, mais pas à la question. Simuler l'injoignabilité par un
        # 401 serait faux — c'est exactement ce que ce test faisait avant le 28/10/2026, et
        # un 401 veut dire « demande disparue », pas « panne ».
        double.confirm_status = 500
        double.status_state = "sans_route"

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "pair_injoignable"
        assert etat.json()["attempt"] is not None


async def test_le_nom_declare_survit_a_l_appariement(blank_db: str, tmp_path: Path) -> None:
    # Après la confirmation, la tentative disparaît : sans report sur le pair, le nom sous
    # lequel ce module est connu à l'autre bout serait perdu.
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})

        pair = await stack.client.get("/api/identity/peer")

        assert pair.json()["declared_name"] == NOM


@pytest.mark.parametrize("sale", ["  314159  ", "314 159", "\n314159\n", "31 41 59", "\t314159"])
async def test_un_code_colle_sale_est_nettoye_et_non_refuse(
    blank_db: str, tmp_path: Path, sale: str
) -> None:
    """Un code circule par copier-coller : il arrivera sale, et le refuser pour cela
    reviendrait à refuser le bon code.

    Éprouvé par l'API, et pas seulement par l'écran : mesuré le 28/10/2026 sur machine de
    test, seul le navigateur nettoyait et un appel direct rendait 422. Une règle qui ne
    vit que dans un écran est fausse pour tout autre appelant.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )

        reponse = await stack.client.post("/api/identity/pairing/confirm", json={"code": sale})

        assert reponse.status_code == 200, reponse.text
        assert double.bodies[-1] == b'{"code": "314159"}'


@pytest.mark.parametrize("reponse_du_pair", ["inconnue", "disparue"])
async def test_une_demande_disparue_est_lue_comme_un_refus_et_non_comme_une_panne(
    blank_db: str, tmp_path: Path, reponse_du_pair: str
) -> None:
    """Le vrai module d'enrôlement REFUSE l'appel une fois la demande supprimée.

    Il n'a plus aucune clé pour le vérifier, et répondre « inconnue » à un inconnu lui
    dirait que cette origine n'est pas appariée. Ce 401-là n'est donc pas une panne : nous
    AVIONS une demande, donc il veut dire qu'elle a disparu. Le prendre pour une panne
    afficherait « injoignable » là où un humain vient de refuser — trouvé par la campagne
    du 28/10/2026, après que la doublure, elle, répondait obligeamment « inconnue ».
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        double.status_state = reponse_du_pair

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "refusee"


async def test_repointer_le_pair_a_la_main_n_efface_pas_le_nom_declare(
    blank_db: str, tmp_path: Path
) -> None:
    """Le nom déclaré dit sous quel nom CE module est connu à l'autre bout.

    Repointer l'adresse du pair — ce qu'un administrateur fait quand le transport change —
    n'a aucune raison de l'effacer. Trouvé le 28/10/2026 en repointant pour de vrai sur
    machine de test : le nom disparaissait en silence, pendant que l'écran de l'autre bout
    continuait de l'afficher. Une perte silencieuse est pire qu'un refus.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})

        repointe = await stack.client.put(
            "/api/identity/peer",
            json={"base_url": "http://autre-adresse.test", "public_key": double.keypair.public_key},
        )

        assert repointe.status_code == 200
        assert repointe.json()["base_url"] == "http://autre-adresse.test"
        assert repointe.json()["declared_name"] == NOM


async def _apparie(stack: Any, double: EnrolmentDouble) -> None:
    """Appariement complet par les routes : demande, puis code recopié."""
    await stack.client.post("/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM})
    confirme = await stack.client.post(
        "/api/identity/pairing/confirm", json={"code": EXPECTED_CODE}
    )
    assert confirme.status_code == 200, confirme.text


async def test_un_appariement_vivant_est_confirme_par_le_pair(
    blank_db: str, tmp_path: Path
) -> None:
    """L'état « apparié » n'est plus lu localement : il est DEMANDÉ au pair à l'affichage."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "apparie"
        assert etat.json()["peer"] is not None


async def test_un_appariement_que_le_pair_ne_reconnait_plus_se_voit_a_l_ecran(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 6 du ticket d5ffeb33 : la stack révoquée le CONSTATE, et peut refrapper.

    Le pair ne nous appelle jamais : il n'a aucun moyen de nous dire qu'il a révoqué. On
    s'en aperçoit parce qu'il refuse nos appels signés — et c'est le seul signal qui
    existe, le refus étant volontairement opaque de son côté.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        # Le pair a détruit la clé qu'il détenait pour nous : il ne vérifie plus rien de
        # ce que nous signons. C'est exactement ce que fait une révocation chez lui.
        double.expects_public_key = generate_keypair().public_key

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "refuse_par_le_pair"
        # L'appariement reste AFFICHÉ : c'est le dernier connu, et son empreinte est ce
        # qu'on voudra comparer après avoir refrappé. On ne le détruit pas sur la foi
        # d'une réponse distante.
        assert etat.json()["peer"] is not None
        # Et refrapper est possible, ce qui est la seconde moitié du critère.
        double.expects_public_key = ""
        neuve = await stack.client.post(
            "/api/identity/pairing", json={"base_url": PEER_ORIGIN, "name": NOM}
        )
        # 202 : la demande est ouverte, rien n'est acquis. Le pair ne conclut qu'au code.
        assert neuve.status_code == 202, neuve.text


async def test_un_401_du_portillon_du_pair_n_est_pas_un_appariement_rompu(
    blank_db: str, tmp_path: Path
) -> None:
    """Les deux 401 ont la même forme, et seul le code de refus les sépare.

    Mesuré le 28/10/2026 : le portillon d'authentification du pair rend 401 quand la
    route de pair n'existe pas chez lui. Le prendre pour une révocation ferait réapparier
    une stack dont l'appariement est intact.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.ping_refusal = (401, "session_requise")

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "pair_injoignable"


async def test_un_pair_en_panne_ne_rompt_pas_l_appariement(blank_db: str, tmp_path: Path) -> None:
    """Un 500 est une panne, pas une décision : rien ne doit être remis en cause."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie(stack, double)
        double.ping_refusal = (500, "panne")

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "pair_injoignable"
        assert etat.json()["peer"] is not None


# L'adresse où l'administrateur joint le pair, DIFFÉRENTE de l'origine que celui-ci
# déclare : c'est le cas que le portillon du portail a rendu nécessaire le 29/10/2026.
CONTACT = "http://100.74.9.236:8081"


async def _apparie_par(stack: Any, double: EnrolmentDouble, contact: str) -> dict[str, Any]:
    """Appariement complet en COMPOSANT `contact`, quelle que soit l'origine du pair."""
    ouverte = await stack.client.post(
        "/api/identity/pairing", json={"base_url": contact, "name": NOM}
    )
    assert ouverte.status_code == 202, ouverte.text
    conclu = await stack.client.post("/api/identity/pairing/confirm", json={"code": EXPECTED_CODE})
    assert conclu.status_code == 200, conclu.text
    pair: dict[str, Any] = conclu.json()
    return pair


async def test_l_adresse_tapee_est_gardee_et_l_identite_reste_celle_que_le_pair_declare(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 : deux champs, deux rôles. Jusqu'ici le premier était jeté."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        pair = await _apparie_par(stack, double, CONTACT)

        # L'IDENTITÉ est ce que le pair déclare être, pas ce qu'on a tapé.
        assert pair["base_url"] == PEER_ORIGIN
        # L'ADRESSE DE CONTACT est ce qu'on a tapé et composé avec succès.
        assert pair["contact_url"] == CONTACT


async def test_les_appels_sortants_composent_l_adresse_de_contact(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2, et c'est tout l'objet du ticket : on compose où l'on joint."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie_par(stack, double, CONTACT)
        double.dialled.clear()

        etat = await stack.client.get("/api/identity/pairing/state")

        assert etat.json()["state"] == "apparie"
        # L'hôte réellement composé, pas l'origine déclarée : composer l'identité est
        # exactement ce qui n'aboutissait plus dès qu'un intermédiaire s'interposait.
        assert double.dialled == ["100.74.9.236:8081"]


async def test_un_appel_entrant_declarant_l_adresse_de_contact_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : l'origine déclarée se compare à l'IDENTITÉ, et à elle seule.

    Les confondre rendrait acceptable un appel déclarant une origine que le pair n'a
    jamais revendiquée — et l'adresse de contact, elle, est choisie chez nous.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie_par(stack, double, CONTACT)
        entete = sign_call(
            load_private_key(double.keypair.private_pem),
            origin=CONTACT,
            method="POST",
            target=PEER_PING_PATH,
            body=b"{}",
        )

        refus = await stack.anonymous().post(
            PEER_PING_PATH,
            content=b"{}",
            headers={ORIGIN_HEADER: CONTACT, SIGNATURE_HEADER: entete},
        )

        assert refus.status_code == 401
        journal = await stack.pool.fetch(
            "SELECT properties FROM events WHERE type = $1", PEER_REGISTERED_EVENT
        )
        assert journal  # l'appariement a bien eu lieu : le refus n'est pas « aucun pair »


async def test_un_appel_entrant_declarant_l_identite_reste_accepte(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4 : l'adresse de contact différente ne change rien à ce qu'on vérifie."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie_par(stack, double, CONTACT)
        entete = sign_call(
            load_private_key(double.keypair.private_pem),
            origin=PEER_ORIGIN,
            method="POST",
            target=PEER_PING_PATH,
            body=b"{}",
        )

        accepte = await stack.anonymous().post(
            PEER_PING_PATH,
            content=b"{}",
            headers={ORIGIN_HEADER: PEER_ORIGIN, SIGNATURE_HEADER: entete},
        )

        assert accepte.status_code == 200, accepte.text


async def test_le_reappariement_remplace_l_adresse_de_contact(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5 : c'est par le ré-appariement qu'on change l'adresse, pas autrement."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _apparie_par(stack, double, CONTACT)

        autre = "http://100.74.9.236:9999"
        pair = await _apparie_par(stack, double, autre)

        assert pair["contact_url"] == autre
        assert pair["base_url"] == PEER_ORIGIN


async def test_sans_adresse_de_contact_le_pair_est_joint_la_ou_il_se_nomme(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 6 : la déclaration manuelle n'en exige pas une seconde."""
    pair_cle = generate_keypair()
    async with open_stack(blank_db, tmp_path) as stack:
        depose = await stack.client.put(
            "/api/identity/peer",
            json={"base_url": PEER_ORIGIN, "public_key": pair_cle.public_key},
        )

        assert depose.status_code == 200, depose.text
        assert depose.json()["contact_url"] == PEER_ORIGIN
