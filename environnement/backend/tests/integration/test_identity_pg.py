from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest
import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from miles_socle.db.migration_files import file_load_migrations
from miles_socle.db.migrations import resolve_apply_migrations
from miles_socle.secrets.crypto import SecretCipher
from miles_socle.secrets.model import Secret
from miles_socle.secrets.store import db_insert_secret
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER, sign_call
from miles_socle.signing.keys import fingerprint, generate_keypair, load_private_key

from environnement.config import DEFAULT_MIGRATIONS_DIR
from environnement.identity.model import SIGNING_KEY_SLUG, SIGNING_KEY_TYPE
from environnement.identity.service import IDENTITY_CREATED_EVENT, PEER_PING_PATH
from tests.integration.environnement_stack import EnvironnementStack, open_stack, utc_now
from tests.integration.peer_double import PEER_ORIGIN, EnrolmentDouble

pytestmark = pytest.mark.integration


async def _declare_peer(
    stack: EnvironnementStack, public_key: str, base_url: str = PEER_ORIGIN
) -> None:
    reponse = await stack.client.put(
        "/api/identity/peer", json={"base_url": base_url, "public_key": public_key}
    )
    assert reponse.status_code == 200, reponse.text


async def test_l_identite_est_engendree_au_premier_demarrage(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await stack.client.get("/api/identity")

    assert reponse.status_code == 200
    corps = reponse.json()
    assert len(corps["public_key"]) == 43
    assert corps["algorithm"] == "ed25519"
    assert corps["public_key_fingerprint"] == fingerprint(corps["public_key"])


async def test_l_identite_survit_a_un_redemarrage_et_n_est_jamais_regeneree(
    blank_db: str, tmp_path: Path
) -> None:
    """Le critère central du ticket, mesuré ici sur la base : deux démarrages, une identité.

    Le redéploiement réel se constate sur machine de test ; ce qui se prouve ici est la
    propriété dont il dépend — la base est ce qui persiste, et le démarrage ne régénère rien.
    """
    async with open_stack(blank_db, tmp_path) as stack:
        premiere = (await stack.client.get("/api/identity")).json()

    async with open_stack(blank_db, tmp_path) as stack:
        seconde = (await stack.client.get("/api/identity")).json()
        events = await stack.pool.fetch(
            "SELECT id FROM events WHERE type = $1", IDENTITY_CREATED_EVENT
        )

    assert seconde == premiere
    # Un seul event de création : le second démarrage n'a rien posé, et le journal le dit.
    assert len(events) == 1


async def test_la_cle_privee_est_rangee_chiffree_dans_la_table_des_secrets(
    blank_db: str, tmp_path: Path
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        # L'identité naît au premier usage : sans cette lecture, la base est vide et le
        # test passerait à côté de ce qu'il croit vérifier.
        assert (await stack.client.get("/api/identity")).status_code == 200
        ligne = await stack.pool.fetchrow(
            "SELECT secret_type, key_version, nonce, ciphertext FROM secrets WHERE slug = $1",
            SIGNING_KEY_SLUG,
        )
        renvoi = await stack.pool.fetchval(
            "SELECT private_key_secret_slug FROM module_identity WHERE id = 'self'"
        )

    assert ligne is not None
    assert ligne["secret_type"] == SIGNING_KEY_TYPE
    assert renvoi == SIGNING_KEY_SLUG
    # Chiffrée, et non seulement « pas en clair dans une colonne nommée » : le PEM ne se
    # lit nulle part dans la ligne.
    assert b"PRIVATE KEY" not in bytes(ligne["ciphertext"])
    assert len(bytes(ligne["nonce"])) == 12


async def test_la_suppression_de_la_cle_de_signature_est_refusee(
    blank_db: str, tmp_path: Path
) -> None:
    # L'usage déclaré du secret fait refuser la suppression PROPREMENT, en nommant le
    # consommateur, au lieu de laisser l'écran buter sur la clé étrangère.
    async with open_stack(blank_db, tmp_path) as stack:
        assert (await stack.client.get("/api/identity")).status_code == 200

        reponse = await stack.client.delete(f"/api/secrets/{SIGNING_KEY_SLUG}")
        toujours_la = await stack.pool.fetchval(
            "SELECT count(*) FROM secrets WHERE slug = $1", SIGNING_KEY_SLUG
        )

    assert reponse.status_code == 409
    assert reponse.json()["detail"]["code"] == "secret_utilise"
    assert toujours_la == 1


async def test_la_cle_privee_ne_sort_par_aucune_route(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        identite = await stack.client.get("/api/identity")
        liste = await stack.client.get("/api/secrets")
        fiche = await stack.client.get(f"/api/secrets/{SIGNING_KEY_SLUG}")

    for reponse in (identite, liste, fiche):
        assert reponse.status_code == 200, reponse.text
        assert "PRIVATE KEY" not in reponse.text
        assert "private_key" not in reponse.text


async def test_le_pair_s_enregistre_puis_se_remplace_sans_jamais_se_doubler(
    blank_db: str, tmp_path: Path
) -> None:
    premier, second = generate_keypair(), generate_keypair()
    async with open_stack(blank_db, tmp_path) as stack:
        await _declare_peer(stack, premier.public_key)
        avant = (await stack.client.get("/api/identity/peer")).json()

        await _declare_peer(stack, second.public_key, "https://autre-enrolement.test")

        apres = (await stack.client.get("/api/identity/peer")).json()
        lignes = await stack.pool.fetchval("SELECT count(*) FROM enrolment_peer")

    # Un seul appariement par environnement, garanti par le MODÈLE : le ré-appariement
    # remplace, il ne double pas. Deux identités pour une stack n'ont aucun sens.
    assert lignes == 1
    assert apres["public_key"] == second.public_key
    assert apres["base_url"] == "https://autre-enrolement.test"
    # La date d'appariement initial reste : la rotation des clés ne l'efface pas.
    assert apres["created_at"] == avant["created_at"]
    assert apres["updated_at"] >= avant["updated_at"]


async def test_un_second_pair_est_refuse_par_la_base_elle_meme(
    blank_db: str, tmp_path: Path
) -> None:
    # Vérifiable par un appel direct à la base, comme l'exige le ticket : la garantie est
    # dans le modèle, pas seulement dans l'écran ou dans la route.
    async with open_stack(blank_db, tmp_path) as stack:
        await _declare_peer(stack, generate_keypair().public_key)

        with pytest.raises(asyncpg.IntegrityConstraintViolationError):
            await stack.pool.execute(
                "INSERT INTO enrolment_peer (id, base_url, public_key, algorithm, created_at,"
                " updated_at) VALUES ('autre', 'https://tiers.test', $1, 'ed25519', now(), now())",
                generate_keypair().public_key,
            )


async def test_un_appel_signe_du_pair_est_accepte(blank_db: str, tmp_path: Path) -> None:
    """Premier sens : le module d'enrôlement appelle l'environnement, qui vérifie."""
    pair = generate_keypair()
    async with open_stack(blank_db, tmp_path) as stack:
        await _declare_peer(stack, pair.public_key)
        nous = (await stack.client.get("/api/identity")).json()
        entete = sign_call(
            load_private_key(pair.private_pem),
            origin=PEER_ORIGIN,
            method="POST",
            target=PEER_PING_PATH,
            body=b"{}",
        )

        reponse = await stack.anonymous().post(
            PEER_PING_PATH,
            content=b"{}",
            headers={ORIGIN_HEADER: PEER_ORIGIN, SIGNATURE_HEADER: entete},
        )

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {
        "module": "environnement",
        "origin": "http://environnement.test",
        # L'appelant apprend quelle clé a vérifié son appel, et laquelle nous employons :
        # c'est ce qui rend un désaccord de clés diagnosticable après un ré-appariement.
        "verified_key_fingerprint": fingerprint(pair.public_key),
        "own_key_fingerprint": fingerprint(nous["public_key"]),
    }


async def test_un_appel_signe_par_une_cle_inconnue_est_refuse_et_journalise(
    blank_db: str, tmp_path: Path
) -> None:
    """Le cas de rejet du ticket : clé inconnue, refus, et l'incident journalisé avec l'origine."""
    pair, inconnu = generate_keypair(), generate_keypair()
    async with open_stack(blank_db, tmp_path) as stack:
        await _declare_peer(stack, pair.public_key)
        entete = sign_call(
            load_private_key(inconnu.private_pem),
            origin=PEER_ORIGIN,
            method="POST",
            target=PEER_PING_PATH,
            body=b"{}",
        )

        with structlog.testing.capture_logs() as journal:
            reponse = await stack.anonymous().post(
                PEER_PING_PATH,
                content=b"{}",
                headers={ORIGIN_HEADER: PEER_ORIGIN, SIGNATURE_HEADER: entete},
            )

    assert reponse.status_code == 401
    assert reponse.json() == {"detail": "signature_refusee"}
    refus = [ligne for ligne in journal if ligne["event"] == "appel_signe_refuse"]
    assert len(refus) == 1
    assert refus[0]["reason"] == "signature_invalide"
    assert refus[0]["declared_origin"] == PEER_ORIGIN
    assert refus[0]["log_level"] == "warning"


@pytest.mark.parametrize(
    ("entetes", "raison"),
    [
        ({}, "absente"),
        ({ORIGIN_HEADER: PEER_ORIGIN}, "absente"),
        ({SIGNATURE_HEADER: "v1 " + "A" * 86}, "origine_invalide"),
        (
            {ORIGIN_HEADER: "https://tiers.test", SIGNATURE_HEADER: "v1 " + "A" * 86},
            "origine_inattendue",
        ),
    ],
)
async def test_les_appels_mal_presentes_sont_refuses_et_journalises(
    blank_db: str, tmp_path: Path, entetes: dict[str, str], raison: str
) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        await _declare_peer(stack, generate_keypair().public_key)

        with structlog.testing.capture_logs() as journal:
            reponse = await stack.anonymous().post(PEER_PING_PATH, content=b"{}", headers=entetes)

    assert reponse.status_code == 401
    assert [ligne["reason"] for ligne in journal if ligne["event"] == "appel_signe_refuse"] == [
        raison
    ]


async def test_un_appel_de_pair_avant_tout_appariement_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    # Fail closed : tant qu'aucun pair n'est apparié, il n'existe aucune clé qui autorise.
    async with open_stack(blank_db, tmp_path) as stack:
        with structlog.testing.capture_logs() as journal:
            reponse = await stack.anonymous().post(
                PEER_PING_PATH,
                content=b"{}",
                headers={ORIGIN_HEADER: PEER_ORIGIN, SIGNATURE_HEADER: "v1 " + "A" * 86},
            )

    assert reponse.status_code == 401
    assert [ligne["reason"] for ligne in journal if ligne["event"] == "appel_signe_refuse"] == [
        "aucun_pair"
    ]


async def test_le_module_emet_un_appel_signe_que_son_pair_verifie(
    blank_db: str, tmp_path: Path
) -> None:
    """Second sens : l'environnement appelle, et la contrepartie vérifie avec notre clé."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        nous = (await stack.client.get("/api/identity")).json()
        double.expects_public_key = nous["public_key"]
        await _declare_peer(stack, double.keypair.public_key)

        reponse = await stack.client.post("/api/identity/peer/ping")

    assert reponse.status_code == 200, reponse.text
    assert reponse.json() == {
        "module": "enrolement",
        "origin": PEER_ORIGIN,
        "verified_key_fingerprint": fingerprint(nous["public_key"]),
        "own_key_fingerprint": fingerprint(double.keypair.public_key),
    }
    # La contrepartie a bien reçu NOTRE origine, celle qui est signée.
    assert double.received == ["http://environnement.test"]


async def test_un_pair_qui_detient_une_autre_cle_pour_nous_refuse_notre_appel(
    blank_db: str, tmp_path: Path
) -> None:
    # Appariement rompu : le pair répond, et il refuse. Distingué d'un pair injoignable,
    # parce que le remède n'est pas le même — ici, il faut réapparier.
    double = EnrolmentDouble(expects_public_key=generate_keypair().public_key)
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await _declare_peer(stack, double.keypair.public_key)

        reponse = await stack.client.post("/api/identity/peer/ping")

    assert reponse.status_code == 409
    assert reponse.json() == {"detail": "refuse_par_le_pair"}


async def test_sans_pair_il_n_y_a_pas_d_appel_a_emettre(blank_db: str, tmp_path: Path) -> None:
    async with open_stack(blank_db, tmp_path) as stack:
        assert (await stack.client.get("/api/identity/peer")).status_code == 404
        assert (await stack.client.post("/api/identity/peer/ping")).status_code == 404


async def test_une_cle_privee_remplacee_fait_refuser_de_signer(
    blank_db: str, tmp_path: Path
) -> None:
    """La garde de cohérence : mieux vaut refuser de signer que signer avec la mauvaise clé.

    L'écran générique des secrets peut remplacer la valeur de n'importe quel secret, sans
    connaître la portée de celui-ci. S'il remplace la clé de signature, la clé publique
    que le pair détient ne correspond plus : tous nos appels seraient refusés CHEZ LUI, et
    rien ici ne serait rouge. On refuse donc, et on le dit.
    """
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        nous = (await stack.client.get("/api/identity")).json()
        double.expects_public_key = nous["public_key"]
        await _declare_peer(stack, double.keypair.public_key)
        assert (await stack.client.post("/api/identity/peer/ping")).status_code == 200

        autre = generate_keypair()
        remplace = await stack.client.put(
            f"/api/secrets/{SIGNING_KEY_SLUG}/value", json={"value": autre.private_pem}
        )
        assert remplace.status_code == 204, remplace.text

        with structlog.testing.capture_logs() as journal:
            reponse = await stack.client.post("/api/identity/peer/ping")

    assert reponse.status_code == 503
    assert reponse.json() == {"detail": "identite_incoherente"}
    assert [ligne["event"] for ligne in journal if ligne["event"] == "identite_incoherente"] == [
        "identite_incoherente"
    ]


async def test_un_secret_deja_pose_sur_le_slug_de_l_identite_est_refuse_en_nommant_la_cause(
    blank_db: str, tmp_path: Path
) -> None:
    """Refus qui NOMME la cause, au lieu d'une violation d'unicité en erreur de serveur.

    L'écran des secrets admet n'importe quel slug : si quelqu'un a créé celui de
    l'identité à la main, le module ne doit pas adopter en silence un secret dont il ne
    sait rien, ni tomber sur une erreur illisible.
    """
    conn = await asyncpg.connect(blank_db)
    try:
        await resolve_apply_migrations(conn, file_load_migrations(DEFAULT_MIGRATIONS_DIR))
        await db_insert_secret(
            conn,
            SIGNING_KEY_SLUG,
            "Posé à la main",
            "GIT_TOKEN",
            SecretCipher(bytes(range(32))).seal(SIGNING_KEY_SLUG, Secret("peu importe")),
            utc_now(),
        )
    finally:
        await conn.close()

    # Le refus se produit au PREMIER USAGE, puisque c'est là que l'identité naît : le
    # démarrage, lui, n'exige rien de ce schéma.
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await stack.client.get("/api/identity")

    assert reponse.status_code == 503
    assert reponse.json() == {"detail": "slug_de_l_identite_pris"}


async def test_un_pair_qui_repond_autre_chose_n_est_pas_dit_injoignable(
    blank_db: str, tmp_path: Path
) -> None:
    """Troisième cas : le pair répond, mais pas ce qu'on attend — un 404, par exemple.

    C'est l'état réel au 28/10/2026 : le côté enrôlement du protocole n'est pas déployé
    (ticket 6a0daab6). Le dire « injoignable » enverrait chercher un problème de réseau
    qui n'existe pas.
    """
    muet = FastAPI()
    async with open_stack(blank_db, tmp_path, peer_app=muet) as stack:
        await _declare_peer(stack, generate_keypair().public_key)

        reponse = await stack.client.post("/api/identity/peer/ping")

    assert reponse.status_code == 502
    assert reponse.json() == {"detail": "reponse_inattendue_du_pair", "peer_status": 404}


async def test_le_code_de_refus_du_pair_est_journalise_car_le_statut_ne_suffit_pas(
    blank_db: str, tmp_path: Path
) -> None:
    """Un 401 du pair peut venir de son portillon comme de son vérificateur de signature.

    Mesuré le 28/10/2026 : pointé vers le vrai module d'enrôlement, qui n'a pas encore sa
    route de pair, le ping reçoit 401 « session_requise » — pas un désaccord de clés. Le
    statut ne distingue pas les deux, son code de refus le fait, et c'est pour ça qu'il va
    au journal.
    """
    portillon = FastAPI()

    @portillon.post("/api/peer/ping")
    async def refuse() -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": "session_requise"})

    async with open_stack(blank_db, tmp_path, peer_app=portillon) as stack:
        await _declare_peer(stack, generate_keypair().public_key)

        with structlog.testing.capture_logs() as journal:
            reponse = await stack.client.post("/api/identity/peer/ping")

    assert reponse.status_code == 409
    refus = [ligne for ligne in journal if ligne["event"] == "ping_refuse_par_le_pair"]
    assert len(refus) == 1
    assert refus[0]["peer_detail"] == "session_requise"


async def test_un_corps_de_refus_hors_forme_ne_passe_pas_dans_le_journal(
    blank_db: str, tmp_path: Path
) -> None:
    # La réponse d'un autre service n'entre pas telle quelle dans nos journaux : seule une
    # forme de code de refus est recopiée, le reste devient une marque.
    bavard = FastAPI()

    @bavard.post("/api/peer/ping")
    async def refuse() -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": "Trace complète : " + "x" * 400})

    async with open_stack(blank_db, tmp_path, peer_app=bavard) as stack:
        await _declare_peer(stack, generate_keypair().public_key)

        with structlog.testing.capture_logs() as journal:
            await stack.client.post("/api/identity/peer/ping")

    refus = [ligne for ligne in journal if ligne["event"] == "ping_refuse_par_le_pair"]
    assert refus[0]["peer_detail"] == "(sans code)"
