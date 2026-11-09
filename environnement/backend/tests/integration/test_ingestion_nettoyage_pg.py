"""Les RÈGLES DE NETTOYAGE sur une VRAIE base PostgreSQL (story `45543845`).

**C'est ici que le dispositif se prouve, et nulle part ailleurs.** Ce qui est en jeu n'est
pas du code à nous mais la sémantique de clauses sur de vraies lignes : un seuil ISO-8601
comparé à une colonne `text` sans conversion, une marque d'absence vieillie, et un `DELETE
… RETURNING` dont chaque ligne doit laisser un event. Une doublure qui les rejouerait ne
prouverait que la doublure — et une suppression ne se rattrape pas.

**Le temps se fabrique en vieillissant l'ÉTAT, jamais en déplaçant l'horloge** : une marque
d'absence se pousse de quarante jours par un `UPDATE`, une date de fin d'activité est
écrite dans le passé. C'est de l'état en base, donc c'est le bon endroit pour le simuler ;
une horloge injectée aurait éprouvé l'injection.
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

from environnement.ingestion.api_ingest_file import INGEST_FILE_PATH
from environnement.ingestion.cleanup import OBJECT_REMOVED_EVENT
from environnement.ingestion.cleanup_rules import KIND_EXPIRY, KIND_MISSING
from environnement.ingestion.outcome import (
    ANOMALY_CLEANUP_REFUSED,
    STATE_PARTIAL,
    STATE_PROCESSED,
)
from environnement.storages.model import ABSENCE_COLUMN
from tests.integration.bundles import fabrique_nettoyage
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

SOURCE = "magasins-import"
SCHEMA, TABLE = "pudo", "magasins"
M1, M2, M3 = '["M-1"]', '["M-2"]', '["M-3"]'
# Une date très ancienne et une date très lointaine : le verdict ne doit dépendre ni du
# jour où la campagne tourne, ni du fuseau de la machine.
VIEUX = "2020-01-01"
LOIN = "2099-01-01"


def _item(code: str, fin: str | None = LOIN, fin2: str | None = None) -> dict[str, Any]:
    return {"code": code, "nom": f"Magasin {code}", "ville": "Paris", "fin": fin, "fin2": fin2}


def _document(items: list[dict[str, Any]]) -> bytes:
    return json.dumps({"genere_le": "2026-11-09", "magasins": items}).encode()


@dataclass
class _Depot:
    stack: EnvironnementStack
    secret: str

    async def importe(self, items: list[dict[str, Any]], corps: bytes | None = None) -> Any:
        """Dépose, déroule l'import, et rend la ligne d'ingestion."""
        recu = await self.stack.anonymous().post(
            INGEST_FILE_PATH.format(source=SOURCE),
            content=_document(items) if corps is None else corps,
            headers={"X-API-Key": self.secret, "Content-Type": "application/json"},
        )
        assert recu.status_code == 202, recu.text
        await self.stack.resolve_imports()
        return await self.stack.pool.fetchrow(
            "SELECT state, items_read, items_removed, report::text AS report, started_at"
            " FROM ingestions WHERE id = $1",
            recu.json()["id"],
        )

    async def cles(self) -> set[str]:
        rows = await self.stack.pool.fetch(f"SELECT cle FROM {SCHEMA}.{TABLE}")  # noqa: S608
        return {row["cle"] for row in rows}

    async def marques(self) -> set[str]:
        rows = await self.stack.pool.fetch(
            f"SELECT cle FROM {SCHEMA}.{TABLE} WHERE {ABSENCE_COLUMN} IS NOT NULL"  # noqa: S608
        )
        return {row["cle"] for row in rows}

    async def vieillit_les_marques(self, jours: int) -> None:
        """Pousse toutes les marques d'absence de `jours` dans le passé."""
        await self.stack.pool.execute(
            f"UPDATE {SCHEMA}.{TABLE} SET {ABSENCE_COLUMN} = {ABSENCE_COLUMN}"  # noqa: S608
            f" - make_interval(days => $1) WHERE {ABSENCE_COLUMN} IS NOT NULL",
            jours,
        )

    async def pose_a_la_main(self, cle: str, fin: str = LOIN) -> None:
        """Un objet d'origine MANUELLE, comme l'écran en pose un."""
        await self.stack.pool.execute(
            f"INSERT INTO {SCHEMA}.{TABLE}"  # noqa: S608
            " (cle, objet, empreinte, origine, version_modele)"
            " VALUES ($1, $2::jsonb, $3, 'manuel', 1)",
            cle,
            json.dumps({"Code": cle.strip('[]"'), "Libelle": "À la main", "FinActivite": fin}),
            b"\x02" * 32,
        )

    async def events_de_suppression(self) -> list[dict[str, Any]]:
        rows = await self.stack.pool.fetch(
            "SELECT o.object_id, e.properties::text AS properties"
            " FROM events e JOIN event_objects o ON o.event_id = e.id"
            " WHERE e.type = $1 ORDER BY o.object_id",
            OBJECT_REMOVED_EVENT,
        )
        return [{"cle": row["object_id"], **json.loads(row["properties"])} for row in rows]


@asynccontextmanager
async def _ouvre(
    blank_db: str, tmp_path: Path, **declaration: Any
) -> AsyncIterator[tuple[EnvironnementStack, _Depot]]:
    """Une stack qui sert `magasins-import` en mode fichier, avec ses règles de nettoyage."""
    versions = fabrique_nettoyage(tmp_path, **declaration)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        recu = await stack.client.post(
            "/api/api-keys", json={"label": "Transporteur", "sources": [SOURCE]}
        )
        assert recu.status_code == 201, recu.text
        yield stack, _Depot(stack, recu.json()["secret"])


async def test_les_absents_depuis_PLUS_de_N_jours_sortent_et_les_autres_restent(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1, et c'est la raison d'être du délai : il remplace le verrou que
    `9ab435be` posait contre un export tronqué. Un item marqué d'hier reste."""
    async with _ouvre(blank_db, tmp_path, peremption=[]) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2"), _item("M-3")])
        await depot.importe([_item("M-1")])
        assert await depot.marques() == {M2, M3}
        # M-2 et M-3 sont marqués depuis 40 jours ; on reporte M-3, qui perd sa marque et
        # la reprend fraîche à l'import suivant.
        await depot.vieillit_les_marques(40)

        ligne = await depot.importe([_item("M-1"), _item("M-3")])

        assert ligne["state"] == STATE_PROCESSED
        assert ligne["items_removed"] == 1
        assert await depot.cles() == {M1, M3}


async def test_un_item_PERIME_sort_meme_si_le_fichier_le_porte_encore(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2, et c'est la différence entre les deux règles : la péremption ne lit que
    la donnée que l'objet PORTE. Un point relais fermé depuis un mois est périmé même si
    tous les imports le portent."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        ligne = await depot.importe([_item("M-1", fin=VIEUX), _item("M-2", fin=LOIN)])

        assert ligne["items_removed"] == 1
        assert await depot.cles() == {M2}
        # Et il n'a pas eu besoin d'être marqué absent : les deux règles sont
        # indépendantes.
        assert await depot.marques() == set()


async def test_un_item_que_SEULE_une_des_deux_regles_designe_sort(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : deux règles nomment deux motifs de fin de vie, pas une condition
    conjointe. Un « et » logique aurait rendu la seconde inerte dans presque tous les cas."""
    deux = [("$.FinActivite", 10), ("$.FinContrat", 10)]
    async with _ouvre(blank_db, tmp_path, peremption=deux) as (_, depot):
        ligne = await depot.importe(
            [
                _item("M-1", fin=LOIN, fin2=LOIN),
                _item("M-2", fin=VIEUX, fin2=LOIN),
                _item("M-3", fin=LOIN, fin2=VIEUX),
            ]
        )

        assert ligne["items_removed"] == 2
        assert await depot.cles() == {M1}


async def test_AUCUNE_regle_declaree_ne_supprime_rien_et_l_import_se_termine(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4 : le défaut. Un paramétrage déjà écrit ne se met pas à supprimer parce
    qu'une version l'a traversé."""
    async with _ouvre(blank_db, tmp_path, absents_apres_jours=None, peremption=[]) as (_, depot):
        await depot.importe([_item("M-1", fin=VIEUX), _item("M-2")])
        await depot.importe([_item("M-1", fin=VIEUX)])
        await depot.vieillit_les_marques(400)

        ligne = await depot.importe([_item("M-1", fin=VIEUX)])

        assert ligne["state"] == STATE_PROCESSED
        assert ligne["items_removed"] == 0
        assert await depot.cles() == {M1, M2}


async def test_un_item_d_origine_MANUELLE_est_supprime_par_les_DEUX_regles(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5, et c'est l'ARBITRAGE de Gael du 09/11/2026 : « Un point relais saisi à
    la main n'est jamais supprimé : Non pas d'accord. »

    Les deux moitiés sont ici : la règle des absents le sort comme un autre dès que sa
    marque a plus de N jours, et une règle de péremption le sort dès que sa donnée la
    satisfait — alors même que la fusion refuse d'écraser son corps.
    """
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.pose_a_la_main(M2, fin=LOIN)
        await depot.pose_a_la_main(M3, fin=VIEUX)

        # M-3 est PORTÉ par le fichier — donc jamais marqué absent, et la fusion refuse
        # d'écrire son corps —, et il sort quand même : sa donnée est périmée.
        premier = await depot.importe([_item("M-1"), _item("M-3")])

        assert premier["items_removed"] == 1
        assert await depot.cles() == {M1, M2}
        # M-2, lui, est absent du fichier : il est marqué comme un autre.
        assert await depot.marques() == {M2}
        await depot.vieillit_les_marques(40)

        second = await depot.importe([_item("M-1")])

        assert second["items_removed"] == 1
        assert await depot.cles() == {M1}
        regles = {event["cle"]: event["rule"] for event in await depot.events_de_suppression()}
        # Chacun est sorti par SA règle, et l'event le dit : sans quoi on ne saurait pas
        # laquelle des deux règles corriger.
        assert regles == {M2: KIND_MISSING, M3: KIND_EXPIRY}


async def test_un_item_MANUEL_que_le_dernier_import_PORTAIT_ne_sort_pas(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 6, et c'est le cas qui se casserait si quelqu'un rétablissait une exception
    d'origine dans le marquage : la ligne manuelle n'a pas de marque parce que la fin
    d'import l'a LEVÉE (`absence.clear_statement`), alors même que la fusion refuse
    d'écrire son corps."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.pose_a_la_main(M2, fin=LOIN)
        await depot.importe([_item("M-1")])
        assert await depot.marques() == {M2}
        await depot.vieillit_les_marques(40)

        # Le fichier reparle de M-2 : sa marque tombe, et le nettoyage ne le voit plus.
        ligne = await depot.importe([_item("M-1"), _item("M-2")])

        assert ligne["items_removed"] == 0
        assert await depot.cles() == {M1, M2}


async def test_chaque_suppression_ecrit_un_event_qui_porte_l_OBJET_ENTIER(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7, et l'interdit que Gael a posé le premier : une suppression sans trace ne
    se rattrape pas. La ligne n'existe plus — l'event doit permettre de la reposer."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1", fin=VIEUX), _item("M-2")])

        events = await depot.events_de_suppression()

        assert len(events) == 1
        event = events[0]
        assert event["cle"] == M1
        assert event["objet"] == {
            "Code": "M-1",
            "Libelle": "Magasin M-1",
            "Ville": "Paris",
            "FinActivite": VIEUX,
            "FinContrat": None,
        }
        assert event["rule"] == KIND_EXPIRY
        assert event["property"] == "$.FinActivite"
        assert event["days"] == 10
        assert event["storage"] == "magasins"


async def test_le_journal_des_appels_porte_le_compte_en_UNE_ligne_pour_l_import(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 8 : le journal d'events prend une ligne par item supprimé, celui des appels
    en garde UNE pour l'import, avec son compte. Les deux répondent à deux questions."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        ligne = await depot.importe(
            [_item("M-1", fin=VIEUX), _item("M-2", fin=VIEUX), _item("M-3")]
        )

        assert ligne["items_removed"] == 2
        appels = await stack.pool.fetch("SELECT items_removed FROM ingestions")
        assert [row["items_removed"] for row in appels] == [2]
        recu = await stack.client.get(f"/api/ingestion/calls/{(await _dernier(stack))}")
        assert recu.status_code == 200, recu.text
        assert recu.json()["items_removed"] == 2


async def _dernier(stack: EnvironnementStack) -> str:
    return str(
        await stack.pool.fetchval("SELECT id FROM ingestions ORDER BY received_at DESC LIMIT 1")
    )


async def test_un_import_INCOMPLET_ne_supprime_RIEN(blank_db: str, tmp_path: Path) -> None:
    """Critère 9, et c'est la frontière avec l'interdit de `9ab435be` : un import tronqué
    n'a peut-être pas atteint des items qu'il aurait portés. Il ne nettoie donc pas, même
    pour la règle de péremption, qui n'en aurait pourtant rien appris de faux."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        await depot.importe([_item("M-1")])
        assert await depot.marques() == {M2}
        # Les deux règles désigneraient quelque chose : M-2 est absent depuis 40 jours,
        # et M-3 porte une date de fin d'activité dépassée.
        await depot.vieillit_les_marques(40)
        await depot.pose_a_la_main(M3, fin=VIEUX)

        tronque = _document([_item("M-1")])[:-3]
        ligne = await depot.importe([], corps=tronque)

        assert ligne["state"] == STATE_PARTIAL
        assert ligne["items_removed"] is None
        assert await depot.cles() == {M1, M2, M3}
        # La marque n'a pas bougé non plus : un import tronqué ne conclut rien.
        assert await depot.marques() == {M2}


async def test_une_regle_NON_EVALUABLE_refuse_tout_le_nettoyage_et_le_DIT(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 10. La propriété d'une règle de péremption n'est plus projetée : la règle
    est refusée, et RIEN n'est supprimé — y compris par la règle des absents, qui
    désignait pourtant un item. On ne sait pas si elle était censée porter seule.

    Le storage, lui, reste lisible : le refuser rendrait sa table invisible pour une règle
    qui ne concerne que son nettoyage.
    """
    async with _ouvre(blank_db, tmp_path, index=[]) as (stack, depot):
        await depot.importe([_item("M-1"), _item("M-2", fin=VIEUX)])
        await depot.importe([_item("M-1")])
        await depot.vieillit_les_marques(40)

        ligne = await depot.importe([_item("M-1")])

        assert ligne["state"] == STATE_PROCESSED
        assert ligne["items_removed"] is None
        assert await depot.cles() == {M1, M2}
        rapport = json.loads(ligne["report"])
        assert f"{ANOMALY_CLEANUP_REFUSED}:$.FinActivite" in rapport["anomalies"]
        lu = await stack.client.get(f"/api/storages/{TABLE}/objects")
        assert lu.status_code == 200, lu.text


async def test_le_plan_de_la_selection_emprunte_l_INDEX_declare_et_ne_convertit_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 11, vérifiable par `explain` — et c'est la seule façon de le vérifier.

    `enable_seqscan` est coupé le temps de la mesure : sur une table de trois lignes,
    PostgreSQL préfère toujours un parcours, et le test ne dirait alors rien de ce que le
    plan fait sur un storage réel. Ce qu'on prouve est que l'index DÉCLARÉ PEUT servir
    cette clause — ce qu'une conversion de colonne rendrait impossible.
    """
    from environnement.ingestion.cleanup_rules import expiry_rule, scan_statement, threshold

    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        await depot.importe([_item("M-1"), _item("M-2")])
        declared = await stack.app.state.storages.resolve_declared()
        table = next(t for t in declared.tables if t.storage == "magasins")
        regle = expiry_rule(table.expiries[0])
        sql = scan_statement(table, regle)

        async with stack.pool.acquire() as conn:
            await conn.execute("SET enable_seqscan = off")
            plan = "\n".join(
                row["QUERY PLAN"]
                for row in await conn.fetch(
                    f"EXPLAIN {sql}",
                    threshold(regle, stack.app.state.storages.now()),
                    None,
                    None,
                    100,
                )
            )

        assert "magasins__fin" in plan, plan
        # Aucune conversion de la colonne dans le plan : un `::date` s'y lirait, et il
        # aurait perdu l'index en même temps qu'il mettait la requête à la merci d'une
        # seule valeur inconvertible.
        assert "fin_activite)::" not in plan


async def test_une_valeur_qui_n_est_PAS_une_date_ne_fait_pas_tomber_la_selection(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 12, et c'est pour cela qu'on ne convertit pas la colonne : un `::date`
    aurait fait échouer la requête ENTIÈRE sur une seule de ces valeurs, donc n'aurait
    même pas supprimé les items que la règle désigne vraiment.

    Trois formes, trois sorts : « pas une date » et « 1999-… » sont écartées par le motif
    (la seconde est le piège mesuré : elle trie SOUS le seuil), « 2026-02-30 » a la forme
    d'une date sans en être une et c'est la relecture qui l'épargne.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        ligne = await depot.importe(
            [
                _item("M-1", fin="pas une date"),
                _item("M-2", fin="1999-13-45"),
                _item("M-3", fin="2026-02-30"),
            ]
        )

        assert ligne["state"] == STATE_PROCESSED
        assert ligne["items_removed"] == 0
        assert await depot.cles() == {M1, M2, M3}
        # Le cas est DIT là où quelqu'un peut agir : la restitution montre l'item dont la
        # forme passe mais qui n'est pas une date, et dit qu'il ne sortira pas.
        recu = await stack.client.get(f"/api/storages/{TABLE}/nettoyage")
        assert recu.status_code == 200, recu.text
        page = recu.json()
        assert [(o["cle"], o["removable"]) for o in page["objects"]] == [(M3, False)]


async def test_la_restitution_MONTRE_ce_qui_sortirait_sans_rien_supprimer(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 13 : « montre-moi ce que tu supprimerais » doit se répondre sans supprimer.

    Les deux règles sont rendues avec leur compte, et la page est celle d'UNE d'entre
    elles : un item sort pour UNE raison, et une page mêlée ne dirait pas laquelle.
    """
    async with _ouvre(blank_db, tmp_path, peremption=[("$.FinActivite", 10)]) as (stack, depot):
        await depot.importe([_item("M-1"), _item("M-2"), _item("M-3")])
        await depot.importe([_item("M-1")])
        await depot.vieillit_les_marques(40)

        recu = await stack.client.get(f"/api/storages/{TABLE}/nettoyage")

        assert recu.status_code == 200, recu.text
        page = recu.json()
        assert [(r["id"], r["days"], r["designated"]) for r in page["rules"]] == [
            (f"{KIND_MISSING}:{SOURCE}", 30, 2),
            (f"{KIND_EXPIRY}:$.FinActivite", 10, 0),
        ]
        assert page["refused"] == []
        assert page["rule"] == f"{KIND_MISSING}:{SOURCE}"
        assert {o["cle"] for o in page["objects"]} == {M2, M3}
        assert all(o["removable"] for o in page["objects"])
        # Rien n'a été supprimé : c'est une lecture.
        assert await depot.cles() == {M1, M2, M3}

        choisie = await stack.client.get(
            f"/api/storages/{TABLE}/nettoyage?regle={KIND_EXPIRY}:$.FinActivite"
        )
        assert choisie.json()["objects"] == []
        assert (
            await stack.client.get(f"/api/storages/{TABLE}/nettoyage?regle=absents:x")
        ).status_code == 404


async def test_la_restitution_se_PAGINE_dans_un_ordre_stable(blank_db: str, tmp_path: Path) -> None:
    """Critère 13 (suite) : sans ordre total, deux pages consécutives se recouvrent dès
    que deux objets portent la même valeur — ce qui est le cas courant d'une marque posée
    par le même import."""
    async with _ouvre(blank_db, tmp_path, peremption=[]) as (stack, depot):
        await depot.importe([_item(f"M-{n}") for n in range(1, 6)])
        await depot.importe([_item("M-1")])
        await depot.vieillit_les_marques(40)

        pages = []
        for rang in (1, 2):
            recu = await stack.client.get(f"/api/storages/{TABLE}/nettoyage?page={rang}&taille=2")
            assert recu.status_code == 200, recu.text
            pages.append(recu.json())

        assert pages[0]["total"] == 4
        premiers = [o["cle"] for o in pages[0]["objects"]]
        seconds = [o["cle"] for o in pages[1]["objects"]]
        assert len(premiers) == len(seconds) == 2
        assert set(premiers).isdisjoint(seconds)


async def test_un_storage_VIDE_et_un_storage_sans_designe_ne_sont_pas_des_erreurs(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 14 : rien, pas une erreur. Le cas vide est un régime normal."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        vide = await depot.importe([])

        assert vide["state"] == STATE_PROCESSED
        assert vide["items_removed"] == 0
        recu = await stack.client.get(f"/api/storages/{TABLE}/nettoyage")
        assert recu.status_code == 200, recu.text
        assert recu.json()["objects"] == []
        assert [r["designated"] for r in recu.json()["rules"]] == [0, 0]


async def test_un_grand_nombre_d_items_sort_par_FENETRES_sans_tenir_le_lot(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 15, sur un volume qui tient en campagne.

    Ce qui est vérifié n'est pas une durée — elle dépendrait de la machine — mais que le
    balayage franchit plusieurs fenêtres : 250 items désignés pour une fenêtre de 100.
    Aucun lot n'est tenu en mémoire, et chaque fenêtre est une transaction courte.
    """
    async with _ouvre(blank_db, tmp_path, lot_ecriture=50) as (_, depot):
        tous = [_item(f"M-{n}", fin=VIEUX) for n in range(1, 251)]

        ligne = await depot.importe([*tous, _item("M-reste")])

        assert ligne["items_removed"] == 250
        assert await depot.cles() == {'["M-reste"]'}
        assert len(await depot.events_de_suppression()) == 250


async def test_REJOUER_l_import_ne_supprime_rien_de_plus_et_n_ecrit_pas_d_event_en_double(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 16 : le nettoyage est idempotent parce qu'il n'agit que sur ce qui est
    encore là. Ce qui est sorti ne revient pas, donc n'est pas re-supprimé."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.importe([_item("M-1", fin=VIEUX), _item("M-2")])
        avant = await depot.events_de_suppression()

        ligne = await depot.importe([_item("M-1", fin=VIEUX), _item("M-2")])

        # Il est réécrit par l'import, donc re-désigné par la règle : c'est bien UNE
        # suppression de plus, et pas la même deux fois.
        assert ligne["items_removed"] == 1
        apres = await depot.events_de_suppression()
        assert len(apres) == len(avant) + 1
        assert await depot.cles() == {M2}


async def test_la_restitution_demande_une_SESSION(blank_db: str, tmp_path: Path) -> None:
    """Critère 17, première moitié : voir la sélection demande le droit de lecture sur
    l'environnement. Le portillon le tient en fail closed pour toute route `/api`, et ce
    test est ce qui vérifie que la route neuve n'est pas passée dans la liste blanche.

    La seconde moitié — déclencher une suppression demande le droit d'écriture — n'a pas
    de route : le seul déclencheur est le dépôt d'un fichier, qui exige une clé d'API
    octroyée sur la source. Il n'y a rien de plus à tenir ici.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, _):
        recu = await stack.anonymous().get(f"/api/storages/{TABLE}/nettoyage")

        assert recu.status_code in (401, 403), recu.text
