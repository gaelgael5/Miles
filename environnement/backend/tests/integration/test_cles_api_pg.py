"""Les clés d'API d'ingestion de cet environnement, sur une VRAIE base PostgreSQL.

« non l'environnement porte une page pour gérer les clés d'api », « une cle ouvre les
portes qu'on lui octroie » (Gael, 02/11/2026).

Ce qui ne s'éprouve qu'ici : qu'aucune trace de la clé ne reste en clair dans la base ni
dans le journal d'events, que les octrois sont RELUS contre la version servie — donc
qu'une source retirée par une version suivante se signale — et que la révocation vaut dès
l'appel suivant. Aucune doublure ne répond de ça : c'est la base qui garde, et c'est le
paramétrage servi qui dit ce qui existe.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from miles_socle.apikeys.model import KEY_RE, new_key
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.apikeys.model import GRANTS_EVENT, ISSUED_EVENT, REVOKED_EVENT
from tests.integration.bundles import fabrique_parametrage
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import ordonne, sert

pytestmark = pytest.mark.integration

COMPTES = "comptes-pudo"
SITES = "sites-pudo"


async def _emet(
    stack: EnvironnementStack, label: str = "Transporteur", sources: tuple[str, ...] = (COMPTES,)
) -> tuple[dict, str]:
    recu = await stack.client.post("/api/api-keys", json={"label": label, "sources": list(sources)})
    assert recu.status_code == 201, recu.text
    corps = recu.json()
    # La réponse porte un secret : aucun cache, ni navigateur ni intermédiaire.
    assert recu.headers["cache-control"] == "no-store"
    return corps["key"], corps["secret"]


async def test_une_cle_emise_est_rendue_une_fois_et_plus_jamais(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        decrite, secret = await _emet(stack)

        assert KEY_RE.match(secret) is not None
        assert decrite["sources"] == [COMPTES]
        assert decrite["prefix"] == secret[:12]
        # La liste ne porte que le préfixe : la valeur n'y est plus, et aucune route ne
        # la restitue — y compris « pour la recopier ».
        listees = await stack.client.get("/api/api-keys")
        assert listees.status_code == 200, listees.text
        assert secret not in listees.text
        assert [k["prefix"] for k in listees.json()] == [secret[:12]]


async def test_la_valeur_de_la_cle_n_est_nulle_part_en_clair(blank_db: str, tmp_path: Path) -> None:
    """Le cas de rejet qui compte le plus : on le MESURE, on ne le relit pas à l'œil.

    La base entière est passée au crible — toutes les colonnes textuelles de toutes les
    tables du schéma public — plutôt que les seules colonnes qu'on croit concernées : un
    secret qui fuit le fait toujours là où on ne l'a pas cherché.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        _, secret = await _emet(stack)

        colonnes = await stack.pool.fetch(
            "SELECT c.table_name, c.column_name FROM information_schema.columns c"
            " JOIN information_schema.tables t ON t.table_name = c.table_name"
            " WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'"
            " AND c.data_type IN ('text', 'character varying', 'jsonb', 'json')"
        )
        assert colonnes, "aucune colonne inspectée : le test serait vert pour rien"
        for ligne in colonnes:
            trouve = await stack.pool.fetchval(
                f'SELECT count(*) FROM "{ligne["table_name"]}"'  # noqa: S608 — noms du catalogue
                f' WHERE "{ligne["column_name"]}"::text LIKE $1',
                f"%{secret}%",
            )
            assert trouve == 0, f"clé en clair dans {ligne['table_name']}.{ligne['column_name']}"


async def test_une_cle_sans_octroi_n_est_pas_emise(blank_db: str, tmp_path: Path) -> None:
    """Fail closed : une clé qui n'ouvre rien est un secret distribué sans usage."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        refus = await stack.client.post("/api/api-keys", json={"label": "Vide", "sources": []})

        assert refus.status_code == 422, refus.text
        assert refus.json()["detail"] == {"field": "sources", "reason": "vide"}
        assert await stack.pool.fetchval("SELECT count(*) FROM api_keys") == 0


async def test_un_octroi_vers_une_source_non_declaree_est_refuse_en_la_nommant(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        refus = await stack.client.post(
            "/api/api-keys", json={"label": "Fautive", "sources": ["inventee"]}
        )

        assert refus.status_code == 422, refus.text
        detail = refus.json()["detail"]
        assert (detail["reason"], detail["source"]) == ("source_inconnue", "inventee")
        # Les déclarées sont nommées : l'écran corrige sans rappeler une liste.
        assert detail["declared"] == [COMPTES, SITES]
        assert await stack.pool.fetchval("SELECT count(*) FROM api_keys") == 0


async def test_une_cle_ouvre_la_source_octroyee_et_refuse_les_autres(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        _, secret = await _emet(stack, sources=(COMPTES,))

        ouvre = await stack.api_keys.resolve_authenticate(secret, COMPTES)
        ferme = await stack.api_keys.resolve_authenticate(secret, SITES)

        assert ouvre is not None and ouvre.label == "Transporteur"
        # Même résultat qu'une clé inconnue : distinguer offrirait un oracle sur les
        # sources déclarées. La raison précise est au journal.
        assert ferme is None


async def test_une_cle_inconnue_mal_formee_ou_absente_est_refusee(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        _, secret = await _emet(stack)

        assert await stack.api_keys.resolve_authenticate(None, COMPTES) is None
        assert await stack.api_keys.resolve_authenticate("", COMPTES) is None
        assert await stack.api_keys.resolve_authenticate("mlk_pas-une-cle", COMPTES) is None
        # Bien formée, mais émise par personne.
        assert await stack.api_keys.resolve_authenticate(new_key(), COMPTES) is None
        # Le préfixe affiché est public : il ne doit jamais ouvrir.
        assert await stack.api_keys.resolve_authenticate(secret[:12], COMPTES) is None


async def test_une_cle_revoquee_est_refusee_et_la_revocation_se_rejoue_sans_effet(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        decrite, secret = await _emet(stack)

        premiere = await stack.client.post(f"/api/api-keys/{decrite['id']}/revoke")
        seconde = await stack.client.post(f"/api/api-keys/{decrite['id']}/revoke")

        assert premiere.status_code == 200, premiere.text
        assert premiere.json()["revoked_at"] is not None
        assert "x-miles-already-exists" not in premiere.headers
        # Rejouer n'est pas une erreur, et ne réécrit pas la date de révocation.
        assert seconde.status_code == 200, seconde.text
        assert seconde.headers["x-miles-already-exists"] == "true"
        assert seconde.json()["revoked_at"] == premiere.json()["revoked_at"]
        assert await stack.api_keys.resolve_authenticate(secret, COMPTES) is None
        # Elle reste visible : l'effacer rendrait son histoire illisible.
        assert len((await stack.client.get("/api/api-keys")).json()) == 1


async def test_une_cle_revoquee_ne_recoit_plus_d_octroi(blank_db: str, tmp_path: Path) -> None:
    """Elle ne redevient jamais valide : accepter l'écriture laisserait croire le contraire."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        decrite, _ = await _emet(stack)
        await stack.client.post(f"/api/api-keys/{decrite['id']}/revoke")

        refus = await stack.client.put(
            f"/api/api-keys/{decrite['id']}/grants", json={"sources": [SITES]}
        )

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"] == "cle_revoquee"


async def test_les_octrois_sont_remplaces_et_valent_des_l_appel_suivant(
    blank_db: str, tmp_path: Path
) -> None:
    """Remplacés, pas fusionnés : sinon aucun appel ne saurait RETIRER un octroi."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        decrite, secret = await _emet(stack, sources=(COMPTES,))

        change = await stack.client.put(
            f"/api/api-keys/{decrite['id']}/grants", json={"sources": [SITES]}
        )

        assert change.status_code == 200, change.text
        assert change.json()["sources"] == [SITES]
        assert await stack.api_keys.resolve_authenticate(secret, SITES) is not None
        # L'octroi retiré ne vaut plus : aucun cache ne le fait survivre à ce geste.
        assert await stack.api_keys.resolve_authenticate(secret, COMPTES) is None


async def test_un_octroi_dont_la_source_disparait_est_signale_sans_etre_reecrit(
    blank_db: str, tmp_path: Path
) -> None:
    """La v3 retire `sites`, donc sa source. L'octroi reste écrit, et l'écran le dit.

    Ne s'éprouve qu'avec une version qui RETIRE : réécrire l'octroi d'office interdirait
    à une version suivante de ramener la source, et effacerait à qui on avait ouvert quoi.
    """
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        decrite, secret = await _emet(stack, sources=(COMPTES, SITES))
        assert decrite["missing_sources"] == []

        await ordonne(stack, double, versions[3])

        relue = (await stack.client.get("/api/api-keys")).json()[0]
        assert relue["sources"] == [COMPTES, SITES]
        assert relue["missing_sources"] == [SITES]
        # Et la clé est refusée sur la source disparue, pas seulement signalée.
        assert await stack.api_keys.resolve_authenticate(secret, SITES) is None
        assert await stack.api_keys.resolve_authenticate(secret, COMPTES) is not None


async def test_la_date_de_dernier_usage_avance_sur_un_appel_accepte_et_pas_sur_un_refus(
    blank_db: str, tmp_path: Path
) -> None:
    """C'est elle qui permet de révoquer sans risque : « cette clé sert-elle encore ? »"""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        _, secret = await _emet(stack, sources=(COMPTES,))
        assert (await stack.client.get("/api/api-keys")).json()[0]["last_used_at"] is None

        await stack.api_keys.resolve_authenticate(secret, SITES)
        assert (await stack.client.get("/api/api-keys")).json()[0]["last_used_at"] is None

        await stack.api_keys.resolve_authenticate(secret, COMPTES)
        assert (await stack.client.get("/api/api-keys")).json()[0]["last_used_at"] is not None


async def test_chaque_geste_ecrit_son_event_sans_jamais_la_valeur_de_la_cle(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        decrite, secret = await _emet(stack, sources=(COMPTES,))
        await stack.client.put(
            f"/api/api-keys/{decrite['id']}/grants", json={"sources": [COMPTES, SITES]}
        )
        await stack.client.post(f"/api/api-keys/{decrite['id']}/revoke")

        rows = await stack.pool.fetch(
            "SELECT type, properties::text AS p FROM events WHERE type LIKE 'environment.api_key%'"
            " ORDER BY written_at, type"
        )

        assert [r["type"] for r in rows] == [ISSUED_EVENT, GRANTS_EVENT, REVOKED_EVENT]
        assert all(secret not in r["p"] for r in rows)
        assert all(decrite["id"] in r["p"] for r in rows)
        # L'event d'octrois dit lesquels, pour qu'on puisse relire qui avait quoi et quand.
        assert SITES in rows[1]["p"]


async def test_les_sources_offertes_sont_celles_de_la_version_servie(
    blank_db: str, tmp_path: Path
) -> None:
    """L'écran ne propose que ce qui marche, plutôt que de faire découvrir le refus."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        offertes = await stack.client.get("/api/api-keys/sources")

        assert offertes.status_code == 200, offertes.text
        assert offertes.json() == {"sources": [COMPTES, SITES]}

        await ordonne(stack, double, versions[3])

        # La v3 a retiré `sites` : l'écran ne l'offre plus.
        assert (await stack.client.get("/api/api-keys/sources")).json() == {"sources": [COMPTES]}


async def test_une_cle_inconnue_a_la_revocation_est_un_refus_nomme(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        refus = await stack.client.post(f"/api/api-keys/{'0' * 32}/revoke")
        mal_forme = await stack.client.post("/api/api-keys/pas-un-identifiant/revoke")

        assert refus.status_code == 404, refus.text
        assert refus.json()["detail"] == "cle_inconnue"
        # Un identifiant qui n'a pas la forme attendue ne doit pas atteindre la base.
        assert mal_forme.status_code == 404, mal_forme.text
