from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from miles_socle.signing.calls import ORIGIN_HEADER, SIGNATURE_HEADER
from miles_socle.signing.identity_model import SIGNING_KEY_SLUG, SIGNING_KEY_TYPE
from miles_socle.signing.keys import fingerprint, generate_keypair
from miles_socle.signing.protocol import (
    PAIRING_CONFIRM_PATH,
    PAIRING_REQUEST_PATH,
    PEER_PING_PATH,
    PING_BODY,
)

from enrolement.pairing.model import (
    PAIRING_CONFIRMED_EVENT,
    REQUEST_EXPIRED_EVENT,
    REQUEST_OPENED_EVENT,
    PairingClockSkewError,
    PairingRefusedError,
)
from enrolement.pairing.service import PairingService
from enrolement.pairing.totp import STEP_S
from tests.integration.enrolement_stack import PUBLIC_URL, EnrolementStack, open_stack
from tests.integration.environnement_double import EnvironmentDouble, confirm_body

pytestmark = pytest.mark.integration


def _instance(
    stack: EnrolementStack,
    *,
    now: Callable[[], datetime] | None = None,
    request_ttl_s: int | None = None,
) -> PairingService:
    """Une AUTRE instance du module, sur la même base.

    C'est exactement ce que le ticket exige de pouvoir montrer : le secret d'une demande
    est partagé par toutes les instances, jamais tenu en mémoire de processus. L'humain
    lit le code sur l'une et le colle vers l'autre.
    """
    courant = stack.pairing
    return PairingService(
        courant.pool,
        courant.secrets,
        courant.cipher,
        courant.catalog,
        now or courant.now,
        courant.origin,
        courant.http,
        courant.request_ttl_s if request_ttl_s is None else request_ttl_s,
    )


def _fige(instant: datetime, decalage_s: int = 0) -> Callable[[], datetime]:
    """Une horloge ARRÊTÉE. Le décalage entre deux d'entre elles est alors exact."""
    return lambda: instant + timedelta(seconds=decalage_s)


def _slug(origine: str) -> str:
    """Un slug stable tiré de l'origine : deux doublures d'un même test n'en partagent pas."""
    return re.sub(r"[^a-z0-9]+", "-", origine.lower()).strip("-")[:48]


async def _designe(stack: EnrolementStack, double: EnvironmentDouble) -> str:
    """Déclare un environnement et le désigne pour cette demande. Rend son identifiant.

    PRÉCONDITION de toute révélation de code depuis le ticket bf2115cd : sans
    environnement désigné, la route refuse. Les tests de l'appariement y passent par les
    ROUTES, et non par du SQL, pour que la précondition éprouvée soit exactement celle que
    l'écran applique — un montage à la main prouverait seulement que le SQL fonctionne.
    """
    slug = _slug(double.origin)
    cree = await stack.client.post(
        "/api/environments", json={"label": f"Environnement {slug}", "slug": slug}
    )
    assert cree.status_code == 201, cree.text
    environment_id = str(cree.json()["id"])
    designe = await stack.client.put(
        "/api/pairing/requests/environment",
        params={"base_url": double.origin},
        json={"environment_id": environment_id},
    )
    assert designe.status_code == 200, designe.text
    return environment_id


async def _code(stack: EnrolementStack, double: EnvironmentDouble) -> str:
    """Le code révélé — précédé de la désignation, sans laquelle il n'est pas révélable.

    La désignation est faite ici plutôt que dans chaque test : elle est devenue une
    condition d'EXISTENCE du code, pas un sujet de ces tests-là. Ceux qui l'éprouvent pour
    elle-même ne passent pas par cette fonction.
    """
    if not await _est_designee(stack, double):
        await _designe(stack, double)
    reponse = await stack.client.get("/api/pairing/code", params={"base_url": double.origin})
    assert reponse.status_code == 200, reponse.text
    return str(reponse.json()["code"])


async def _est_designee(stack: EnrolementStack, double: EnvironmentDouble) -> bool:
    """Vrai si la demande porte déjà un environnement — une relecture de code n'en pose pas deux."""
    attendues = await stack.client.get("/api/pairing/requests")
    return any(
        d["base_url"] == double.origin and d["environment"] is not None for d in attendues.json()
    )


async def _confirme_par(service: PairingService, double: EnvironmentDouble, code: str) -> None:
    """Confirme en passant par le SERVICE, pour pouvoir lui donner une autre horloge.

    La signature est produite exactement comme sur le réseau : même méthode, même cible,
    même corps. Court-circuiter la route ne court-circuite donc pas la vérification.
    """
    corps = confirm_body(code)
    entetes = double.headers(PAIRING_CONFIRM_PATH, corps)
    await service.resolve_confirm_pairing(
        declared_origin=entetes[ORIGIN_HEADER],
        signature=entetes[SIGNATURE_HEADER],
        method="POST",
        target=PAIRING_CONFIRM_PATH,
        body=corps,
        code=code,
    )


async def _apparie(stack: EnrolementStack, double: EnvironmentDouble) -> None:
    async with stack.anonymous() as pair:
        assert (await double.knock(pair)).status_code == 202
        reponse = await double.confirm(pair, await _code(stack, double))
    assert reponse.status_code == 200, reponse.text


async def test_un_environnement_qui_frappe_ouvre_une_demande_en_attente(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        async with stack.anonymous() as pair:
            reponse = await double.knock(pair)

        assert reponse.status_code == 202
        assert reponse.json()["base_url"] == double.origin
        attendues = await stack.client.get("/api/pairing/requests")
        assert [d["base_url"] for d in attendues.json()] == [double.origin]
        # L'écran montre l'EMPREINTE, pas la clé : c'est elle qu'un humain compare à ce
        # que l'autre module affiche avant d'accepter.
        assert attendues.json()[0]["public_key_fingerprint"] == fingerprint(
            double.keypair.public_key
        )
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type = $1", REQUEST_OPENED_EVENT
            )
            == 1
        )


async def test_aucune_cle_privee_ne_traverse_le_reseau_dans_aucun_sens(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère central du ticket, et il s'éprouve sur les OCTETS réellement échangés.

    Pas sur l'intention : on relit le corps qui part et celui qui revient, et on y cherche
    la marque d'une clé privée PEM. Un champ ajouté par mégarde ferait rougir ce test.
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        montant = double.knock_body()
        async with stack.anonymous() as pair:
            await double.knock(pair)
            descendant = await double.confirm(pair, await _code(stack, double))

    assert b"PRIVATE KEY" not in montant
    assert b"private" not in montant.lower()
    assert b"PRIVATE KEY" not in descendant.content
    assert b"private" not in descendant.content.lower()
    # Et ce qui revient est bien la MOITIÉ publique attendue, pas une chaîne vide qui
    # passerait les deux assertions précédentes sans rien prouver.
    assert len(descendant.json()["public_key"]) == 43


async def test_une_demande_non_signee_est_refusee_sans_rien_ecrire(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        reponse = await pair.post(PAIRING_REQUEST_PATH, content=double.knock_body())

        assert reponse.status_code == 401
        # Le refus vient de la ROUTE, pas du portillon : la preuve que le chemin est bien
        # ouvert aux appels de machine, et qu'il se défend lui-même.
        assert reponse.json()["detail"] == "appariement_refuse"
        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 0


async def test_une_demande_signee_par_une_autre_cle_que_celle_deposee_est_refusee(
    blank_db: str, tmp_path: Path
) -> None:
    """Sans cette vérification, n'importe qui déposerait la clé d'un autre.

    L'attaquant signerait de sa propre clé et déposerait celle de sa victime — ou
    l'inverse — sous une origine qu'il ne contrôle pas. La signature lie le dépôt à la
    possession de la clé déposée.
    """
    double = EnvironmentDouble()
    etrangere = generate_keypair()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        # Le nom est présent et valide : ce qui est éprouvé ici est la SIGNATURE, et un
        # corps incomplet ferait refuser avant qu'elle ne soit regardée.
        corps = json.dumps({"public_key": etrangere.public_key, "name": "Recette"}).encode()
        reponse = await pair.post(
            PAIRING_REQUEST_PATH, content=corps, headers=double.headers(PAIRING_REQUEST_PATH, corps)
        )

        assert reponse.status_code == 401
        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 0


async def test_frapper_deux_fois_ne_cree_qu_une_demande_et_renouvelle_le_secret(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        async with stack.anonymous() as pair:
            await double.knock(pair)
            premier = await _code(stack, double)
            await double.knock(pair)
            second = await _code(stack, double)

        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 1
        # Deux codes lus dans la MÊME fenêtre : s'ils diffèrent, c'est le secret qui a
        # changé — ce qu'aucune comparaison de dates ne prouverait.
        assert premier != second


async def test_le_code_colle_apparie_les_deux_modules(blank_db: str, tmp_path: Path) -> None:
    """Le cas nominal, bout en bout du côté enrôlement (critère 1 du ticket)."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        async with stack.anonymous() as pair:
            await double.knock(pair)
            reponse = await double.confirm(pair, await _code(stack, double))

        assert reponse.status_code == 200
        rendu = reponse.json()
        # Ce que l'environnement reçoit : NOTRE origine et NOTRE clé publique. C'est le
        # second dépôt, celui qui rend l'échange mutuel.
        assert rendu["base_url"] == PUBLIC_URL
        assert rendu["algorithm"] == "ed25519"
        identite = await stack.client.get("/api/pairing/identity")
        assert rendu["public_key"] == identite.json()["public_key"]
        # La demande est brûlée, et le pair existe.
        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 0
        pairs = await stack.client.get("/api/pairing/peers")
        assert [p["base_url"] for p in pairs.json()] == [double.origin]
        assert pairs.json()[0]["public_key"] == double.keypair.public_key
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type = $1", PAIRING_CONFIRMED_EVENT
            )
            == 1
        )


async def test_apres_appariement_un_appel_signe_est_accepte(blank_db: str, tmp_path: Path) -> None:
    """L'autre moitié du critère 1 : l'appariement se CONSTATE par un appel signé."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double)

        async with stack.anonymous() as pair:
            reponse = await double.ping(pair)

        assert reponse.status_code == 200, reponse.text
        pong = reponse.json()
        assert pong["module"] == "enrolement"
        assert pong["origin"] == PUBLIC_URL
        # Les deux empreintes rendent un désaccord de clés diagnosticable : l'appelant
        # compare ce qu'il croit détenir à ce qui a réellement vérifié son appel.
        assert pong["verified_key_fingerprint"] == fingerprint(double.keypair.public_key)
        identite = await stack.client.get("/api/pairing/identity")
        assert pong["own_key_fingerprint"] == identite.json()["public_key_fingerprint"]


async def test_un_appel_signe_par_une_cle_inconnue_est_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double)
        # Même origine, autre clé : c'est le cas qui compte, parce qu'il ressemble à un
        # appariement valide de tous les côtés sauf celui qui décide.
        imposteur = EnvironmentDouble(origin=double.origin)

        async with stack.anonymous() as pair:
            refuse = await imposteur.ping(pair)
            nu = await pair.post(PEER_PING_PATH, content=PING_BODY)

        assert refuse.status_code == 401
        assert refuse.json()["detail"] == "signature_refusee"
        assert nu.status_code == 401


async def test_un_code_faux_est_refuse_et_la_demande_reste_en_attente(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        async with stack.anonymous() as pair:
            await double.knock(pair)
            juste = await _code(stack, double)
            faux = "000000" if juste != "000000" else "111111"
            reponse = await double.confirm(pair, faux)

            assert reponse.status_code == 401
            assert reponse.json()["detail"] == "appariement_refuse"
            # La demande survit : une faute de frappe est bien plus fréquente qu'une
            # attaque, et la détruire punirait la première.
            assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 1
            # Et le bon code marche toujours après l'erreur.
            assert (await double.confirm(pair, juste)).status_code == 200


async def test_un_code_rejoue_est_refuse_meme_dans_la_meme_fenetre(
    blank_db: str, tmp_path: Path
) -> None:
    """Le code est BRÛLÉ à l'usage : la fenêtre n'y change rien."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        code = await _code(stack, double)

        assert (await double.confirm(pair, code)).status_code == 200
        rejeu = await double.confirm(pair, code)

        assert rejeu.status_code == 401
        assert rejeu.json()["detail"] == "appariement_refuse"


async def test_la_fenetre_precedente_passe_et_les_plus_anciennes_nomment_l_horloge(
    blank_db: str, tmp_path: Path
) -> None:
    """Critères 4 et 17 ensemble : la tolérance, et ce qu'on dit au-delà.

    Le code est lu maintenant et présenté à une instance dont l'horloge avance : c'est
    exactement la forme qu'a la dérive entre deux serveurs.
    """
    double = EnvironmentDouble()
    # Les deux horloges sont FIGÉES, et l'écart entre elles est exact. Les prendre de
    # l'horloge réelle ferait basculer le test une fois sur trente, à la seconde près où
    # la fenêtre change — l'échec un jour sur cent que la discipline de test proscrit.
    lecture = datetime.now(UTC)
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        # Sans environnement désigné, le code n'est pas révélable (ticket bf2115cd) :
        # la précondition est posée par les routes, comme à l'écran.
        await _designe(stack, double)
        code = (await _instance(stack, now=_fige(lecture)).resolve_request_code(double.origin)).code

        # Une fenêtre d'écart : accepté, parce que recopier un code prend quelques secondes.
        await _confirme_par(_instance(stack, now=_fige(lecture, STEP_S)), double, code)
        assert await stack.pool.fetchval("SELECT count(*) FROM environment_peer") == 1

        await double.knock(pair)
        code = (await _instance(stack, now=_fige(lecture)).resolve_request_code(double.origin)).code
        with pytest.raises(PairingClockSkewError) as refus:
            await _confirme_par(_instance(stack, now=_fige(lecture, 5 * STEP_S)), double, code)

        assert refus.value.offset_windows == -5
        assert refus.value.drift_s == -5 * STEP_S
        # La demande n'est PAS brûlée : ce n'est pas un code faux, et l'humain doit
        # pouvoir réessayer une fois les horloges remises d'accord.
        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 1


async def test_le_code_d_une_demande_ne_vaut_pas_pour_une_autre(
    blank_db: str, tmp_path: Path
) -> None:
    """Deux demandes simultanées : chacune a son secret (critère 7)."""
    premier = EnvironmentDouble(origin="http://env-un.test")
    second = EnvironmentDouble(origin="http://env-deux.test")
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await premier.knock(pair)
        await second.knock(pair)

        croise = await second.confirm(pair, await _code(stack, premier))

        assert croise.status_code == 401
        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 2


async def test_un_code_lu_par_une_instance_est_accepte_par_une_autre(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 6 : le secret est en base, jamais en mémoire de processus.

    L'humain lit le code sur l'instance qui sert son écran et le colle vers une autre.
    Sans état partagé, l'appariement échouerait par intermittence — et le diagnostic
    partirait sur l'horloge.
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        await _designe(stack, double)
        lectrice = _instance(stack)

        code = (await lectrice.resolve_request_code(double.origin)).code
        # Collé vers l'instance servie par l'application, qui est un autre objet.
        reponse = await double.confirm(pair, code)

        assert reponse.status_code == 200, reponse.text


async def test_une_demande_jamais_traitee_expire_et_son_secret_disparait(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        code = await _code(stack, double)
        echeance = await stack.pool.fetchval("SELECT expires_at FROM pairing_request")

        # Une instance dont l'horloge a dépassé l'échéance : c'est le même effet que le
        # temps qui passe, sans faire attendre la campagne.
        apres = _instance(stack, now=lambda: echeance + timedelta(seconds=1))
        assert await apres.resolve_pending_requests() == []

        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 0
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM events WHERE type = $1", REQUEST_EXPIRED_EVENT
            )
            == 1
        )
        # Le code ne vaut plus rien, et le refus ne dit pas pourquoi.
        assert (await double.confirm(pair, code)).status_code == 401


async def test_le_refus_humain_detruit_la_demande_et_son_secret(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10 : l'environnement reçoit un refus explicite plutôt qu'une attente sans fin."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        code = await _code(stack, double)

        refus = await stack.client.delete(
            "/api/pairing/requests", params={"base_url": double.origin}
        )

        assert refus.status_code == 204
        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 0
        assert (await double.confirm(pair, code)).status_code == 401
        # Et le code n'est plus lisible : il n'y a plus de secret à lire.
        assert (
            await stack.client.get("/api/pairing/code", params={"base_url": double.origin})
        ).status_code == 404


async def test_un_module_d_enrolement_apparie_plusieurs_environnements(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 15 : c'est le cas NOMINAL, et chacun a ses propres clés."""
    doubles = [EnvironmentDouble(origin=f"http://env-{rang}.test") for rang in range(3)]
    async with open_stack(blank_db, tmp_path) as stack:
        for double in doubles:
            await _apparie(stack, double)

        pairs = (await stack.client.get("/api/pairing/peers")).json()
        assert {p["base_url"] for p in pairs} == {d.origin for d in doubles}
        assert len({p["public_key"] for p in pairs}) == 3
        async with stack.anonymous() as pair:
            for double in doubles:
                assert (await double.ping(pair)).status_code == 200


async def test_le_reappariement_remplace_la_cle_sans_laisser_de_doublon(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 14 : jamais deux identités pour une même stack."""
    ancien = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, ancien)
        creation = await stack.pool.fetchval("SELECT created_at FROM environment_peer")
        nouveau = EnvironmentDouble(origin=ancien.origin)

        await _apparie(stack, nouveau)

        lignes = await stack.pool.fetch(
            "SELECT base_url, public_key, created_at FROM environment_peer"
        )
        assert len(lignes) == 1
        assert lignes[0]["public_key"] == nouveau.keypair.public_key
        # La date d'appariement initial survit : elle date un fait, que la rotation des
        # clés ne défait pas.
        assert lignes[0]["created_at"] == creation
        async with stack.anonymous() as pair:
            assert (await nouveau.ping(pair)).status_code == 200
            # L'ancienne clé ne vaut plus rien, et c'est le but du remplacement.
            assert (await ancien.ping(pair)).status_code == 401


async def test_la_cle_privee_du_module_est_rangee_comme_secret_chiffre(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 16 : rangée comme les autres secrets du produit, jamais en clair."""
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double)

        ligne = await stack.pool.fetchrow(
            "SELECT secret_type, ciphertext FROM secrets WHERE slug = $1", SIGNING_KEY_SLUG
        )
        assert ligne["secret_type"] == SIGNING_KEY_TYPE
        assert b"PRIVATE KEY" not in bytes(ligne["ciphertext"])
        # L'usage déclaré fait refuser la suppression PROPREMENT, au lieu de laisser
        # l'écran des secrets buter sur la clé étrangère et rendre une erreur de serveur.
        suppression = await stack.client.delete(f"/api/secrets/{SIGNING_KEY_SLUG}")
        assert suppression.status_code == 409
        assert (
            await stack.pool.fetchval(
                "SELECT count(*) FROM secrets WHERE slug = $1", SIGNING_KEY_SLUG
            )
            == 1
        )


async def test_les_routes_d_administration_de_l_appariement_exigent_une_session(
    blank_db: str, tmp_path: Path
) -> None:
    """Fail closed : seules les routes de PAIR échappent à la session, et elles se signent."""
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as visiteur:
        for chemin in ("/api/pairing/requests", "/api/pairing/peers", "/api/pairing/identity"):
            reponse = await visiteur.get(chemin)

            assert reponse.status_code == 401, chemin
            assert reponse.json()["detail"] == "session_requise", chemin


async def test_une_origine_mal_formee_est_refusee_avant_tout_usage(
    blank_db: str, tmp_path: Path
) -> None:
    """Entrée utilisateur employée ensuite comme clé de base ET comme données associées."""
    async with open_stack(blank_db, tmp_path) as stack:
        reponse = await stack.client.get(
            "/api/pairing/code", params={"base_url": "https://enrolement.test/chemin"}
        )

        assert reponse.status_code == 422
        assert reponse.json()["detail"] == "base_url"


async def test_le_refus_ne_distingue_pas_le_code_de_la_demande(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : les deux cas rendent le MÊME refus, au statut comme au détail.

    Les séparer offrirait un oracle — savoir qu'une demande existe pour une origine
    donnée, ou approcher le code en distinguant les deux causes.
    """
    inconnu = EnvironmentDouble(origin="http://jamais-vu.test")
    connu = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await connu.knock(pair)
        juste = await _code(stack, connu)
        faux = "000000" if juste != "000000" else "111111"

        sans_demande = await inconnu.confirm(pair, faux)
        mauvais_code = await connu.confirm(pair, faux)

        assert sans_demande.status_code == mauvais_code.status_code == 401
        assert sans_demande.json() == mauvais_code.json()


async def test_le_service_refuse_de_conclure_sans_adresse_publique(
    blank_db: str, tmp_path: Path
) -> None:
    """Sans origine, l'environnement ne saurait pas quelle origine attendre de nos appels.

    Il les refuserait tous, et le diagnostic partirait sur les clés. Mieux vaut refuser
    l'appariement que le conclure à moitié.
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)
        code = await _code(stack, double)
        courant = stack.pairing
        aveugle = PairingService(
            courant.pool,
            courant.secrets,
            courant.cipher,
            courant.catalog,
            courant.now,
            None,
            courant.request_ttl_s,
        )

        with pytest.raises(PairingRefusedError):
            await _confirme_par(aveugle, double, code)


async def test_le_nom_declare_accompagne_la_demande_puis_l_appariement(
    blank_db: str, tmp_path: Path
) -> None:
    double = EnvironmentDouble(name="  Recette nord  ")
    async with open_stack(blank_db, tmp_path) as stack:
        async with stack.anonymous() as pair:
            await double.knock(pair)

            demandes = (await stack.client.get("/api/pairing/requests")).json()
            # Les espaces de bord disparaissent : le nom arrive d'un formulaire, à l'autre bout.
            assert demandes[0]["name"] == "Recette nord"

            await double.confirm(pair, await _code(stack, double))

        pairs = (await stack.client.get("/api/pairing/peers")).json()
        assert pairs[0]["name"] == "Recette nord"
        # Le référentiel des devices n'existe pas encore : NUL, et surtout pas zéro, qui
        # afficherait « aucun device » sur un écran qui ne sait pas compter.
        assert pairs[0]["device_count"] is None


@pytest.mark.parametrize("nom", ["", "   ", "A" * 81, "deux\nlignes", "tabulation\tinterdite"])
async def test_un_nom_declare_inacceptable_est_refuse(
    blank_db: str, tmp_path: Path, nom: str
) -> None:
    """Le nom vient d'un tiers que personne n'a encore authentifié : borné et sans contrôle.

    Un retour à la ligne casse une ligne de journal structuré, et l'écran de l'autre bout
    afficherait une demande sur deux lignes qu'on lirait comme deux demandes.
    """
    double = EnvironmentDouble(name=nom)
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        reponse = await double.knock(pair)

        assert reponse.status_code == 422
        assert reponse.json()["detail"] == "name"
        assert await stack.pool.fetchval("SELECT count(*) FROM pairing_request") == 0


async def test_deux_demandes_de_meme_nom_restent_distinguables(
    blank_db: str, tmp_path: Path
) -> None:
    """Le nom déclaré n'identifie RIEN : c'est l'URL qui distingue, et elle est unique."""
    premier = EnvironmentDouble(origin="http://env-un.test", name="Recette")
    second = EnvironmentDouble(origin="http://env-deux.test", name="Recette")
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await premier.knock(pair)
        await second.knock(pair)

        demandes = (await stack.client.get("/api/pairing/requests")).json()

        assert [d["name"] for d in demandes] == ["Recette", "Recette"]
        assert {d["base_url"] for d in demandes} == {premier.origin, second.origin}
        # Et les instants de réception les séparent aussi, ce que l'écran affiche.
        assert demandes[0]["created_at"] <= demandes[1]["created_at"]


async def test_un_nom_qui_ressemble_a_du_balisage_est_stocke_tel_quel(
    blank_db: str, tmp_path: Path
) -> None:
    # L'échappement appartient à l'affichage. Le mutiler ici abîmerait un nom légitime en
    # donnant l'illusion d'une protection, et masquerait un écran qui oublierait d'échapper.
    hostile = '<img src=x onerror="alert(1)"> & Cie'
    double = EnvironmentDouble(name=hostile)
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        assert (await double.knock(pair)).status_code == 202

        demandes = (await stack.client.get("/api/pairing/requests")).json()
        assert demandes[0]["name"] == hostile


async def test_l_environnement_peut_demander_ou_en_est_sa_demande(
    blank_db: str, tmp_path: Path
) -> None:
    """Sans cette route, son écran afficherait « en attente » pour toujours.

    Son code refusé et sa demande disparue lui rendent le même refus opaque — c'est
    voulu —, donc rien d'autre ne lui dirait qu'un humain a dit non.
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await double.knock(pair)

        en_attente = await double.status(pair)

        assert en_attente.status_code == 200
        assert en_attente.json()["state"] == "en_attente"
        assert en_attente.json()["expires_at"] is not None

        await stack.client.delete("/api/pairing/requests", params={"base_url": double.origin})
        refuse = await double.status(pair)

        # 401 et non « inconnue » : la demande supprimée, ce module ne détient plus aucune
        # clé pour vérifier cet appel. Répondre quoi que ce soit confirmerait à un inconnu
        # que cette origine n'est pas appariée. L'environnement, lui, sait qu'il AVAIT une
        # demande : pour lui, ce 401 veut dire qu'elle a disparu, et son écran le traduit
        # en « refusée » ou « expirée » selon l'échéance qu'il a reçue en frappant.
        assert refuse.status_code == 401


async def test_chacun_ne_lit_que_sa_propre_demande(blank_db: str, tmp_path: Path) -> None:
    """La route d'état est signée : elle ne dit rien à qui ne détient pas la clé déposée."""
    legitime = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack, stack.anonymous() as pair:
        await legitime.knock(pair)
        # Même origine, autre clé : c'est le cas qui compte, parce qu'il ressemble à une
        # demande valide de tous les côtés sauf celui qui décide.
        imposteur = EnvironmentDouble(origin=legitime.origin)

        assert (await imposteur.status(pair)).status_code == 401
        # Et une origine dont ce module n'a jamais entendu parler n'apprend rien non plus :
        # répondre « inconnue » lui confirmerait qu'elle n'est pas déjà appariée.
        assert (
            await EnvironmentDouble(origin="http://jamais-vu.test").status(pair)
        ).status_code == 401


async def test_apres_appariement_l_etat_reste_interrogeable(blank_db: str, tmp_path: Path) -> None:
    """Un environnement qui vient d'être apparié repose la question avant de rafraîchir.

    Sa demande a disparu : sans recours à la clé du pair déjà apparié, sa dernière
    question serait refusée juste après son succès, et son écran dirait « refusée ».
    """
    double = EnvironmentDouble()
    async with open_stack(blank_db, tmp_path) as stack:
        await _apparie(stack, double)

        async with stack.anonymous() as pair:
            apres = await double.status(pair)

        assert apres.status_code == 200
        assert apres.json() == {"state": "inconnue", "expires_at": None}
