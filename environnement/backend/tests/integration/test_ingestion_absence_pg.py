"""La MARQUE D'ABSENCE sur une VRAIE base PostgreSQL (story `82bc9dca`).

**C'est ici que le dispositif se prouve, et nulle part ailleurs.** Ce qui est en jeu n'est
pas du code à nous mais la sémantique de deux instructions sur de vraies lignes : un
`UPDATE … WHERE absent_depuis IS NULL AND vu_le < $2 AND NOT EXISTS (…)` et le
`ON CONFLICT … SET absent_depuis = NULL` de la fusion. Une doublure qui les rejouerait ne
prouverait que la doublure — et une marque posée à tort est INVISIBLE le jour où elle est
posée : elle devient une suppression de masse au bout du délai déclaré.

Le marquage ne lit aucune règle de nettoyage et ne supprime rien : il rend visible ce qui
est absent. La suppression est un autre ticket, et c'est cette date-là qu'elle lira.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.ingestion.api_ingest import INGEST_PATH
from environnement.ingestion.api_ingest_file import INGEST_FILE_PATH
from environnement.ingestion.model import ELEMENT
from environnement.ingestion.outcome import (
    REJECT_MODEL,
    STATE_FAILED_IMPORT,
    STATE_PARTIAL,
    STATE_PROCESSED,
)
from environnement.storages.model import ABSENCE_COLUMN
from tests.integration.bundles import fabrique_import_fichier
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

SOURCE = "magasins-import"
SCHEMA, TABLE = "pudo", "magasins"
M1, M2, M3 = '["M-1"]', '["M-2"]', '["M-3"]'


def _item(code: str, ville: str = "Paris") -> dict[str, Any]:
    return {"code": code, "nom": f"Magasin {code}", "ville": ville, "postes": 3}


def _document(items: list[dict[str, Any]]) -> bytes:
    return json.dumps({"genere_le": "2026-11-09", "magasins": items}).encode()


@dataclass
class _Depot:
    stack: EnvironnementStack
    secret: str

    async def fichier(self, corps: bytes) -> str:
        """Dépose un document et rend l'identifiant de l'ingestion mise en file."""
        recu = await self.stack.anonymous().post(
            INGEST_FILE_PATH.format(source=SOURCE),
            content=corps,
            headers={"X-API-Key": self.secret, "Content-Type": "application/json"},
        )
        assert recu.status_code == 202, recu.text
        return str(recu.json()["id"])

    async def importe(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        """Dépose, déroule l'import, et rend la ligne d'ingestion."""
        ingestion = await self.fichier(_document(items))
        await self.stack.resolve_imports()
        return await self.ingestion(ingestion)

    async def ingestion(self, ingestion_id: str) -> dict[str, Any]:
        row = await self.stack.pool.fetchrow(
            "SELECT state, items_read, report::text AS report, started_at"
            " FROM ingestions WHERE id = $1",
            ingestion_id,
        )
        return dict(row)

    async def lignes(self) -> dict[str, Any]:
        rows = await self.stack.pool.fetch(
            f"SELECT cle, objet::text AS objet, empreinte, vu_le, modifie_le, origine,"  # noqa: S608
            f" {ABSENCE_COLUMN} FROM {SCHEMA}.{TABLE}"
        )
        return {row["cle"]: row for row in rows}

    async def marques(self) -> dict[str, Any]:
        """Les clés marquées absentes, avec la date de leur marque."""
        return {
            cle: ligne[ABSENCE_COLUMN]
            for cle, ligne in (await self.lignes()).items()
            if ligne[ABSENCE_COLUMN] is not None
        }

    async def pose_a_la_main(self, cle: str) -> None:
        """Un objet d'origine MANUELLE, comme l'écran en pose un."""
        await self.stack.pool.execute(
            f"INSERT INTO {SCHEMA}.{TABLE}"  # noqa: S608
            " (cle, objet, empreinte, origine, version_modele)"
            " VALUES ($1, $2::jsonb, $3, 'manuel', 1)",
            cle,
            json.dumps({"Code": cle.strip('[]"'), "Libelle": "À la main"}),
            b"\x02" * 32,
        )


@asynccontextmanager
async def _ouvre(
    blank_db: str, tmp_path: Path, **declaration: Any
) -> AsyncIterator[tuple[EnvironnementStack, _Depot]]:
    """Une stack qui sert la source `magasins-import` en mode fichier, avec sa clé."""
    versions = fabrique_import_fichier(tmp_path, **declaration)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        recu = await stack.client.post(
            "/api/api-keys", json={"label": "Transporteur", "sources": [SOURCE]}
        )
        assert recu.status_code == 201, recu.text
        yield stack, _Depot(stack, recu.json()["secret"])


async def test_un_import_complet_marque_ce_que_le_fichier_ne_portait_pas(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 : les items absents portent la marque, ceux du fichier non.

    Et la date de la marque est celle de CET import : c'est elle qui donnera « absent
    depuis N jours », et une date prise ailleurs ferait compter le délai de travers.
    """
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2"), _item("M-3")])

        ligne = await depot.importe([_item("M-1")])

        assert ligne["state"] == STATE_PROCESSED
        assert await depot.marques() == {
            M2: ligne["started_at"],
            M3: ligne["started_at"],
        }


async def test_un_second_import_sans_l_item_NE_RETOUCHE_PAS_sa_marque(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2, et c'est LA décision de Gael : « si à l'import suivant l'item n'est pas
    dedans non plus on ne retouche pas l'item déjà marqué missing ».

    Sans cela, la date se rafraîchirait à chaque import, le délai serait inatteignable, et
    aucun item ne sortirait jamais — un dispositif de nettoyage qui ne nettoie pas.
    """
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1")])
        premiere = (await depot.marques())[M2]

        await depot.importe([_item("M-1")])

        assert (await depot.marques())[M2] == premiere


async def test_un_import_qui_reporte_l_item_LEVE_sa_marque_et_le_compteur_repart(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : c'est ce qui fait du délai une protection contre un export tronqué.

    Un fichier amputé marque des items à tort ; le fichier complet du lendemain les
    démarque, et rien n'a été supprimé entre-temps. Si l'item disparaît de nouveau plus
    tard, la marque est reposée à la date de CE nouvel import, pas de l'ancien.
    """
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1")])
        ancienne = (await depot.marques())[M2]

        await depot.importe([_item("M-1"), _item("M-2")])
        assert await depot.marques() == {}

        reposee = await depot.importe([_item("M-1")])
        marques = await depot.marques()
        assert marques[M2] > ancienne
        assert marques[M2] == reposee["started_at"]


async def test_un_import_INCOMPLET_leve_les_marques_qu_il_porte_et_n_en_pose_aucune(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4. L'asymétrie est voulue et sûre dans les deux sens : ce qu'il a vu, il
    l'a vu ; ce qu'il n'a pas vu, il ne l'a peut-être pas ATTEINT — le document s'est
    interrompu, et marquer dessus poserait des marques de masse injustifiées.
    """
    async with _ouvre(blank_db, tmp_path, transaction_unifiee=False) as (stack, depot):
        await depot.importe([_item("M-1"), _item("M-2"), _item("M-3")])
        await depot.importe([_item("M-3")])
        assert set(await depot.marques()) == {M1, M2}

        entier = _document([_item("M-1"), _item("M-2"), _item("M-3")])
        tronque = await depot.fichier(entier[: entier.index(b'"M-3"')])
        await stack.resolve_imports()

        ligne = await depot.ingestion(tronque)
        assert ligne["state"] == STATE_PARTIAL
        # Deux choses dans cette seule assertion, et chacune est un sens de l'asymétrie :
        # M-1 et M-2, écrits par l'import tronqué, perdent leur marque ; M-3, que le
        # document n'a PAS atteint, n'en reçoit pas — son `vu_le` est pourtant antérieur
        # au début de cet import, donc il était candidat.
        assert await depot.marques() == {}


async def test_un_import_en_ECHEC_ne_pose_ni_ne_leve_aucune_marque(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5 : rien n'a été écrit, donc rien n'a été vu ni oublié."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1")])
        avant = await depot.marques()

        echoue = await depot.fichier(json.dumps({"autre": [_item("M-1")]}).encode())
        await stack.resolve_imports()

        assert (await depot.ingestion(echoue))["state"] == STATE_FAILED_IMPORT
        assert await depot.marques() == avant


async def test_un_depot_UNITAIRE_leve_la_marque_sans_jamais_en_poser(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 6 : un dépôt en mode `element` ne prétend pas porter l'image complète — il
    ne dit rien de ce qu'il ne contient pas — mais il reparle de l'item qu'il porte.

    La source est servie en mode fichier ET unitaire pour ce test : c'est le seul moyen de
    confronter les deux modes au même storage, qui est précisément le cas où une marque
    posée par le mauvais mode se verrait.
    """
    async with _ouvre(blank_db, tmp_path, modes=(True, False, True)) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1")])
        assert set(await depot.marques()) == {M2}

        recu = await depot.stack.anonymous().post(
            INGEST_PATH.format(source=SOURCE, mode=ELEMENT),
            json=_item("M-2", ville="Lille"),
            headers={"X-API-Key": depot.secret},
        )

        assert recu.status_code == 201, recu.text
        assert await depot.marques() == {}


async def test_un_item_du_fichier_que_le_MODELE_REJETTE_n_est_pas_marque_absent(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7, et c'est l'écueil du ticket.

    La marque dit « la source ne parle plus de cet item », pas « l'objet est invalide ».
    Les confondre ferait supprimer, au bout du délai, les items que la source envoie
    fidèlement et que le modèle refuse — c'est-à-dire exactement ceux qu'il faut aller
    corriger. Rien n'a avancé leur `vu_le`, puisque rien n'a été écrit pour eux : c'est
    l'aire de préparation, qui porte une ligne par item LU, qui les protège.
    """
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2"), _item("M-3")])

        # Un nombre là où le modèle du storage attend une chaîne ou null : l'objet est
        # refusé APRÈS la transformation, donc sa clé s'extrait — et c'est elle qui le
        # protège.
        fautif = {**_item("M-2"), "ville": 42}
        ligne = await depot.importe([_item("M-1"), fautif])

        rapport = json.loads(ligne["report"])
        rejete = [o for o in rapport["objects"] if o["outcome"] == "rejete"]
        assert [o["reason"] for o in rejete] == [REJECT_MODEL]
        # La clé est nommée dans le compte-rendu : c'est elle qui protège l'item, et elle
        # dit aussi à la source lequel de ses items corriger.
        assert [o["key"] for o in rejete] == [M2]
        # M-2 n'est PAS marqué : le document en parlait. M-3, dont le document ne parle
        # plus, l'est.
        assert set(await depot.marques()) == {M3}


async def test_un_item_d_origine_MANUELLE_n_est_jamais_marque(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 8 : aucun import ne le porte jamais, donc son `vu_le` est toujours ancien.

    Le marquer le sortirait au premier nettoyage, et au pire moment, puisque personne ne
    surveille un objet posé à la main. Même raison que son exclusion de l'écrasement.
    """
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1")])
        await depot.pose_a_la_main(M3)

        await depot.importe([_item("M-1")])

        assert await depot.marques() == {}
        assert (await depot.lignes())[M3]["origine"] == "manuel"


async def test_la_pose_et_la_levee_ne_touchent_ni_le_corps_ni_l_empreinte(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 9. L'empreinte dit si la SOURCE a changé l'objet, et une marque n'est pas
    une modification venue de la source — la vérifier sur le seul corps aurait laissé
    passer une empreinte recalculée."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        avant = (await depot.lignes())[M2]

        await depot.importe([_item("M-1")])
        marque = (await depot.lignes())[M2]
        await depot.importe([_item("M-1"), _item("M-2")])
        levee = (await depot.lignes())[M2]

        for apres in (marque, levee):
            assert apres["objet"] == avant["objet"]
            assert apres["empreinte"] == avant["empreinte"]
        # La POSE ne touche pas non plus les dates : elle n'est ni une vue ni une
        # modification de la source. La levée, elle, passe par l'écriture de l'import,
        # qui avance `vu_le` comme pour tout item porté.
        assert marque["vu_le"] == avant["vu_le"]
        assert marque["modifie_le"] == avant["modifie_le"]
        assert levee["vu_le"] > avant["vu_le"]


async def test_un_item_marque_reste_rendu_par_la_lecture_et_sa_marque_se_voit(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10 : on doit pouvoir VOIR ce qui est absent avant qu'une règle ne le
    supprime. Un filtre implicite sur la marque aurait fait disparaître des objets de
    l'écran sans que personne ne l'ait demandé."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1")])

        recu = await stack.client.get(f"/api/storages/{TABLE}/objects")

        assert recu.status_code == 200, recu.text
        page = recu.json()
        assert page["total"] == 2
        marques = {o["cle"]: o["absent_depuis"] for o in page["objects"]}
        assert marques[M1] is None
        assert marques[M2] is not None


async def test_un_fichier_qui_porte_tout_et_un_storage_vide_ne_marquent_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 11 : ni marque, ni erreur. Le cas vide est un régime normal."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        premier = await depot.importe([])
        assert premier["state"] == STATE_PROCESSED
        assert await depot.lignes() == {}

        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1"), _item("M-2")])

        assert await depot.marques() == {}


async def test_rejouer_le_MEME_fichier_deux_fois_ne_change_aucune_marque(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 12 : le marquage est idempotent, comme l'écriture qu'il suit."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1")])
        avant = await depot.marques()

        await depot.importe([_item("M-1")])

        assert await depot.marques() == avant


async def test_le_marquage_ne_tient_aucune_cle_en_memoire_et_ne_reecrit_aucun_objet(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 13, sur un volume qui tient en campagne.

    Ce qui est vérifié n'est pas une durée — elle dépendrait de la machine — mais les deux
    choses que l'interdit du ticket nomme : la sélection des absents est UNE instruction
    qui ne reçoit aucune clé en paramètre, et aucun corps d'objet n'est réécrit. L'ensemble
    des clés du fichier se dérive de `vu_le` et de l'instant de l'import ; le tenir aurait
    rendu en mémoire ce que la lecture en flux évite — un export réel en compte des
    centaines de milliers (168 775 mesurées sur `pudo.accounts`).
    """
    async with _ouvre(blank_db, tmp_path, lot_ecriture=50) as (_, depot):
        tous = [_item(f"M-{n}") for n in range(1, 301)]
        await depot.importe(tous)
        avant = await depot.lignes()

        await depot.importe(tous[:100])

        apres = await depot.lignes()
        assert len(apres) == 300
        assert len(await depot.marques()) == 200
        # Aucun corps réécrit : l'empreinte des 300 lignes est celle d'avant, marquées
        # comme non marquées.
        assert all(apres[cle]["empreinte"] == avant[cle]["empreinte"] for cle in avant)
