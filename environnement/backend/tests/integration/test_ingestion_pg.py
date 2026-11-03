"""Le point d'entrée d'ingestion, sur une VRAIE base PostgreSQL (story 4d4fdcef).

Ce qui ne s'éprouve qu'ici : que le lot BRUT est en base avant toute transformation, que
la clé d'idempotence rend le MÊME accusé sans rien persister deux fois, et que le refus
d'une clé sans octroi ne laisse aucune trace de dépôt. La contrainte d'unicité partielle
sur l'idempotence est tenue par la base ; aucune doublure n'en dit rien.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from miles_socle.apikeys.model import new_key
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.ingestion.api_ingest import CHALLENGE, IDEMPOTENCY_HEADER, INGEST_PATH
from environnement.ingestion.model import (
    BATCH,
    ELEMENT,
    FILE,
    RECEIVED_EVENT,
)
from environnement.ingestion.outcome import STATE_PROCESSED
from tests.integration.bundles import fabrique_parametrage
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import ordonne, sert

pytestmark = pytest.mark.integration

COMPTES = "comptes-pudo"
SITES = "sites-pudo"
LOT = [{"AccountId": "A-1", "Postes": 3}, {"AccountId": "A-2", "Postes": 12}]


def _adresse(source: str, mode: str) -> str:
    return INGEST_PATH.format(source=source, mode=mode)


async def _cle(stack: EnvironnementStack, sources: tuple[str, ...] = (COMPTES,)) -> str:
    recu = await stack.client.post(
        "/api/api-keys", json={"label": "Transporteur", "sources": list(sources)}
    )
    assert recu.status_code == 201, recu.text
    secret: str = recu.json()["secret"]
    return secret


async def _depose(
    stack: EnvironnementStack,
    *,
    source: str = COMPTES,
    mode: str = BATCH,
    cle: str | None,
    corps: Any = None,
    content: bytes | None = None,
    content_type: str | None = "application/json",
    idempotence: str | None = None,
) -> Any:
    entetes: dict[str, str] = {}
    if cle is not None:
        entetes["X-API-Key"] = cle
    if content_type is not None:
        entetes["Content-Type"] = content_type
    if idempotence is not None:
        entetes[IDEMPOTENCY_HEADER] = idempotence
    charge = (
        content if content is not None else json.dumps(LOT if corps is None else corps).encode()
    )
    return await stack.anonymous().post(_adresse(source, mode), content=charge, headers=entetes)


async def test_un_lot_depose_est_persiste_brut_et_accuse(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        recu = await _depose(stack, cle=cle)

        assert recu.status_code == 201, recu.text
        accuse = recu.json()
        assert accuse["source"] == COMPTES
        assert (accuse["mode"], accuse["object_count"]) == (BATCH, 2)
        # « traite » et non « recu » depuis la story d680e811 : les modes `element` et
        # `tableau` transforment et écrivent DANS l'appel, et l'accusé porte le sort de
        # chaque objet. Le lot brut reste persisté AVANT cela — c'est ce que la ligne
        # relue ci-dessous vérifie, et c'est la condition du rejeu.
        assert (accuse["state"], accuse["replayed"]) == (STATE_PROCESSED, False)
        # Le lot BRUT est retrouvable par l'identifiant de l'accusé : c'est la condition
        # du rejeu, et elle doit tenir AVANT toute transformation.
        ligne = await stack.pool.fetchrow(
            "SELECT raw::text AS raw, entry_model, version_number, key_label, size_bytes"
            " FROM ingestions WHERE id = $1",
            accuse["id"],
        )
        assert json.loads(ligne["raw"]) == LOT
        assert ligne["entry_model"] == "pudo/accounts"
        assert ligne["version_number"] == 1
        assert ligne["key_label"] == "Transporteur"
        assert ligne["size_bytes"] > 0


async def test_le_depot_ecrit_son_event_dont_l_auteur_est_la_CLE(
    blank_db: str, tmp_path: Path
) -> None:
    """Pas une personne : l'annuaire `apikey` le dit. Sans cela, l'historique
    emprunterait l'identité de l'administrateur qui a émis la clé."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        recu = await _depose(stack, cle=cle)

        event = await stack.pool.fetchrow(
            "SELECT author_directory, author_subject, properties::text AS p FROM events"
            " WHERE type = $1",
            RECEIVED_EVENT,
        )
        assert event is not None
        assert event["author_directory"] == "apikey"
        proprietes = json.loads(event["p"])
        assert proprietes["source"] == COMPTES
        assert proprietes["object_count"] == 2
        # Jamais la valeur de la clé, nulle part.
        assert cle not in event["p"]
        # L'event est rattaché au dépôt, donc son histoire se relit par l'objet.
        rattache = await stack.pool.fetchval(
            "SELECT count(*) FROM event_objects WHERE object_kind = 'ingestion' AND object_id = $1",
            recu.json()["id"],
        )
        assert rattache == 1


async def test_un_depot_sans_cle_est_refuse_et_dit_comment_en_presenter_une(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])

        recu = await _depose(stack, cle=None)

        assert recu.status_code == 401, recu.text
        assert recu.json()["detail"]["code"] == "authentification_requise"
        assert recu.headers["www-authenticate"] == CHALLENGE
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0


async def test_une_cle_sans_octroi_sur_cette_source_est_refusee_sans_rien_persister(
    blank_db: str, tmp_path: Path
) -> None:
    """Le fail closed du dépôt. Et le refus est le MÊME qu'une clé absente : distinguer
    offrirait un oracle sur les sources déclarées."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack, sources=(SITES,))

        recu = await _depose(stack, cle=cle)

        assert recu.status_code == 401, recu.text
        assert recu.json()["detail"]["code"] == "authentification_requise"
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0


async def test_une_cle_revoquee_ou_inconnue_est_refusee(blank_db: str, tmp_path: Path) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        emise = await stack.client.post(
            "/api/api-keys", json={"label": "À révoquer", "sources": [COMPTES]}
        )
        cle = emise.json()["secret"]
        await stack.client.post(f"/api/api-keys/{emise.json()['key']['id']}/revoke")

        revoquee = await _depose(stack, cle=cle)
        inconnue = await _depose(stack, cle=new_key())

        assert (revoquee.status_code, inconnue.status_code) == (401, 401)
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0


async def test_une_source_retiree_par_la_version_servie_ferme_le_point_d_entree(
    blank_db: str, tmp_path: Path
) -> None:
    """Éprouvé en faisant SERVIR une version qui RETIRE la source : une version qui
    ajoute ne prouve rien. C'est le défaut trouvé le 02/11/2026 — l'octroi vit en base,
    la source vit dans git, et rien ne propage la disparition."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack, sources=(COMPTES, SITES))
        assert (
            await _depose(stack, source=SITES, mode=ELEMENT, cle=cle, corps={"Id": "S-1"})
        ).status_code == 201

        await ordonne(stack, double, versions[3])

        ferme = await _depose(stack, source=SITES, mode=ELEMENT, cle=cle, corps={"Id": "S-2"})
        assert ferme.status_code == 401, ferme.text
        # Et la source encore déclarée reste ouverte : on n'a pas tout fermé.
        assert (await _depose(stack, cle=cle)).status_code == 201


async def test_la_cle_d_idempotence_rend_le_meme_accuse_sans_rien_persister_deux_fois(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        premier = await _depose(stack, cle=cle, idempotence="lot-2026-11-02")
        second = await _depose(stack, cle=cle, idempotence="lot-2026-11-02")

        assert premier.status_code == 201, premier.text
        # 200 et non 201 : un rejeu n'a rien créé, et l'appelant doit pouvoir le
        # distinguer sans lire le corps.
        assert second.status_code == 200, second.text
        assert second.json()["id"] == premier.json()["id"]
        assert second.json()["replayed"] is True
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 1


async def test_le_meme_lot_SANS_cle_d_idempotence_produit_deux_ingestions(
    blank_db: str, tmp_path: Path
) -> None:
    """La déduplication se fait à l'écriture par empreinte, pas à la réception : refuser
    un lot parce qu'il ressemble au précédent interdirait de redéposer une image."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        premier = await _depose(stack, cle=cle)
        second = await _depose(stack, cle=cle)

        assert (premier.status_code, second.status_code) == (201, 201)
        assert premier.json()["id"] != second.json()["id"]
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 2


async def test_deux_cles_peuvent_employer_la_meme_cle_d_idempotence(
    blank_db: str, tmp_path: Path
) -> None:
    """Sa portée est la clé de l'appelant : deux partenaires ne se marchent pas dessus,
    et aucun ne peut faire rendre à l'autre un accusé qu'il n'a pas obtenu."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        premiere = await _cle(stack)
        seconde = await _cle(stack)

        un = await _depose(stack, cle=premiere, idempotence="lot-1")
        deux = await _depose(stack, cle=seconde, idempotence="lot-1")

        assert (un.status_code, deux.status_code) == (201, 201)
        assert un.json()["id"] != deux.json()["id"]


async def test_un_tableau_vide_est_accepte_et_un_corps_vide_refuse(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        vide = await _depose(stack, cle=cle, corps=[])
        rien = await _depose(stack, cle=cle, content=b"")

        assert vide.status_code == 201, vide.text
        assert vide.json()["object_count"] == 0
        assert rien.status_code == 400, rien.text
        assert rien.json()["detail"]["code"] == "corps_vide"
        # Le tableau vide a bien été persisté : zéro objet est une ingestion.
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 1


async def test_les_refus_de_forme_portent_leur_code_et_leur_statut(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        invalide = await _depose(stack, cle=cle, content=b'[{"a": 1,}]')
        objet = await _depose(stack, cle=cle, corps={"AccountId": "A-1"})
        type_faux = await _depose(stack, cle=cle, content_type="text/plain")

        assert invalide.status_code == 400
        assert invalide.json()["detail"]["code"] == "json_invalide"
        assert "ligne" in invalide.json()["detail"]["detail"]
        assert objet.status_code == 400
        assert objet.json()["detail"]["code"] == "tableau_attendu"
        assert type_faux.status_code == 415
        assert type_faux.json()["detail"]["code"] == "type_de_contenu_inattendu"
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0


async def test_un_mode_que_l_entree_n_expose_pas_est_refuse_sans_rien_persister(
    blank_db: str, tmp_path: Path
) -> None:
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack, sources=(COMPTES, SITES))

        # `sites-pudo` n'expose que `element` dans la v1.
        refus = await _depose(stack, source=SITES, mode=BATCH, cle=cle, corps=[{"Id": "S-1"}])

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"]["code"] == "mode_non_declare"
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0


async def test_le_mode_fichier_declare_est_refuse_comme_non_servi(
    blank_db: str, tmp_path: Path
) -> None:
    """La v2 coche `fichier` sur `comptes-pudo`. Refusé nommément : accepter sans effet
    laisserait croire qu'un lot a été pris en charge."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[2])
        cle = await _cle(stack)

        refus = await _depose(stack, mode=FILE, cle=cle, corps=[])

        assert refus.status_code == 409, refus.text
        assert refus.json()["detail"]["code"] == "mode_non_servi"


async def test_une_source_inconnue_ou_un_mode_inventé_sont_refuses_apres_la_cle(
    blank_db: str, tmp_path: Path
) -> None:
    """Après la clé, et jamais avant : un appelant anonyme n'apprend pas quelles sources
    existent en lisant les refus."""
    versions = fabrique_parametrage(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        cle = await _cle(stack)

        # Octroyée sur `comptes-pudo` seulement : une autre source est d'abord une
        # affaire d'octroi, donc 401 — pas 404.
        autre = await _depose(stack, source="inventee", cle=cle)
        anonyme = await _depose(stack, source="inventee", cle=None)
        mode = await _depose(stack, mode="massif", cle=cle)

        assert autre.status_code == 401, autre.text
        assert anonyme.status_code == 401, anonyme.text
        assert mode.status_code == 404, mode.text
        assert mode.json()["detail"]["code"] == "mode_inconnu"


async def test_sans_version_servie_rien_n_est_recu(blank_db: str, tmp_path: Path) -> None:
    """Et le point d'entrée n'existait pas avant : une stack sans version ne déclare
    aucune source, donc le refus ne ferme rien qui fût ouvert."""
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        refus = await _depose(stack, cle=new_key())

        assert refus.status_code == 401, refus.text
        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0
