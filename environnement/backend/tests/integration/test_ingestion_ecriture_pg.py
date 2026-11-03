"""L'écriture DIFFÉRENTIELLE d'un lot, sur une VRAIE base PostgreSQL (story d680e811).

**C'est ici, et nulle part ailleurs, que l'écriture différentielle se prouve.** La
doublure des tests unitaires n'exécute pas le `ON CONFLICT` : elle rend ce que
`db_write_object` attend, donc un test qui prétendrait y mesurer le delta mesurerait la
doublure. Ce que PostgreSQL seul peut dire :

- que `vu_le` avance sur une ligne inchangée alors que `modifie_le` ne bouge pas — les
  deux `CASE` de l'instruction, qui comparent l'empreinte en base à celle qui arrive ;
- que les colonnes projetées sont **dérivées** du jsonb, et non écrites ;
- qu'un objet d'origine `manuel` est écarté par la clause `WHERE` du `DO UPDATE`, sans
  que même sa date de dernière vue bouge ;
- qu'une interruption en cours de traitement ne laisse ni lot ni ligne, parce que les deux
  gestes sont dans la même transaction.

**L'instant est INJECTÉ** (`_Horloge`) : les deux dates sont ce que cette suite éprouve, et
les comparer à l'horloge du système les rendrait vraies à une tolérance près — un test qui
dépend de l'horloge échoue un jour sur cent. Ici chaque dépôt a son instant connu, et
« la date n'a pas bougé » est une égalité, pas un ordre.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from miles_socle.testing.enrolment_double import EnrolmentDouble

from environnement.ingestion.api_ingest import IDEMPOTENCY_HEADER, INGEST_PATH
from environnement.ingestion.model import BATCH
from environnement.ingestion.outcome import (
    REJECT_MANUAL,
    REJECT_MODEL,
    REJECTED,
    STATE_FAILED,
    STATE_PROCESSED,
    UNCHANGED,
    WRITTEN,
)
from environnement.ingestion.store_objects import IMPORT_ORIGIN, MANUAL_ORIGIN
from environnement.ingestion.writeback import OBJECT_WRITTEN_EVENT
from tests.integration.bundles import fabrique_import
from tests.integration.environnement_stack import EnvironnementStack, open_stack
from tests.integration.versions import sert

pytestmark = pytest.mark.integration

SOURCE = "magasins-import"
SCHEMA, TABLE = "pudo", "magasins"
# La colonne DÉRIVÉE du storage `magasins`, indexé sur `$.Ville`.
PROJETEE = "ville"
DEBUT = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)


def _objet(code: str, nom: str, ville: str, postes: int, emis: str = "T0") -> dict[str, Any]:
    """Un objet de la SOURCE, dans sa forme brute — minuscules, et un champ de trop.

    `emis_le` n'est lu par aucune étape de la chaîne : c'est lui qui rend le critère 4
    éprouvable, parce qu'une source réelle horodate ses envois et qu'un hash du message
    source réécrirait tout à chaque remise.
    """
    return {"code": code, "nom": nom, "ville": ville, "postes": postes, "emis_le": emis}


LOT = [_objet("M-1", "Gare du Nord", "Paris", 3), _objet("M-2", "Part-Dieu", "Lyon", 7)]
# La clé telle que `key_of` la compose : un tableau JSON, même pour un seul jpath.
M1, M2, M3 = '["M-1"]', '["M-2"]', '["M-3"]'


@dataclass
class _Horloge:
    """L'instant que le service lit. `avance` marque le dépôt suivant."""

    instant: datetime = DEBUT

    def __call__(self) -> datetime:
        return self.instant

    def avance(self, minutes: int = 1) -> datetime:
        self.instant += timedelta(minutes=minutes)
        return self.instant


@asynccontextmanager
async def _ouvre(blank_db: str, tmp_path: Path) -> AsyncIterator[tuple[EnvironnementStack, Any]]:
    """Une stack qui SERT le paramétrage d'import, avec son horloge et sa clé d'API."""
    versions = fabrique_import(tmp_path)
    double = EnrolmentDouble()
    async with open_stack(blank_db, tmp_path, peer_app=double.app()) as stack:
        await sert(stack, double, versions[1])
        horloge = _Horloge()
        # Le service est reconstruit avec l'horloge injectée, et REPOSÉ sur l'état de
        # l'application : c'est de là que la route le prend. Reconstruit plutôt que
        # modifié parce qu'il est gelé — et il l'est pour qu'on ne le modifie pas en
        # production.
        stack.app.state.ingestion = replace(stack.ingestion, now=horloge)
        secret = await _cle(stack)
        yield stack, _Depot(stack, secret, horloge)


async def _cle(stack: EnvironnementStack) -> str:
    recu = await stack.client.post(
        "/api/api-keys", json={"label": "Transporteur", "sources": [SOURCE]}
    )
    assert recu.status_code == 201, recu.text
    secret: str = recu.json()["secret"]
    return secret


@dataclass
class _Depot:
    """De quoi déposer un lot et relire ce que la base en a fait."""

    stack: EnvironnementStack
    secret: str
    horloge: _Horloge

    async def depose(
        self, corps: Any, *, idempotence: str | None = None, avance: bool = True
    ) -> Any:
        """Dépose un lot. `avance` fait passer l'horloge à l'instant du dépôt suivant."""
        if avance:
            self.horloge.avance()
        entetes = {"X-API-Key": self.secret, "Content-Type": "application/json"}
        if idempotence is not None:
            entetes[IDEMPOTENCY_HEADER] = idempotence
        return await self.stack.anonymous().post(
            INGEST_PATH.format(source=SOURCE, mode=BATCH),
            content=json.dumps(corps).encode(),
            headers=entetes,
        )

    async def lignes(self) -> dict[str, Any]:
        """La table du storage, par clé. L'objet est relu TEXTE : un jsonb revient en
        chaîne d'asyncpg, et comparer sans convertir comparerait des caractères."""
        colonnes = f"cle, objet::text AS objet, empreinte, origine, vu_le, modifie_le, {PROJETEE}"
        rows = await self.stack.pool.fetch(
            f"SELECT {colonnes}, version_modele FROM {SCHEMA}.{TABLE}"  # noqa: S608
        )
        return {row["cle"]: row for row in rows}

    async def pose_manuel(self, cle: str, objet: dict[str, Any], vu_le: datetime) -> None:
        """Un objet d'origine MANUELLE, comme une saisie ou un appel MCP en poserait.

        Écrit directement : le geste qui le produira est une autre story, et ce qui
        s'éprouve ici est que l'import ne l'écrase pas.
        """
        await self.stack.pool.execute(
            f"INSERT INTO {SCHEMA}.{TABLE}"  # noqa: S608
            " (cle, objet, empreinte, origine, vu_le, modifie_le, version_modele)"
            " VALUES ($1, $2::jsonb, $3, $4, $5, $5, 1)",
            cle,
            json.dumps(objet),
            b"\x11" * 32,
            MANUAL_ORIGIN,
            vu_le,
        )


def _transforme(code: str, nom: str, ville: str, postes: int) -> dict[str, Any]:
    """Ce que la chaîne produit : les noms du MODÈLE, et rien du champ d'émission."""
    return {"Code": code, "Libelle": nom, "Ville": ville, "Postes": postes}


def _sorts(reponse: Any) -> dict[int, dict[str, Any]]:
    return {o["position"]: o for o in reponse.json()["report"]["objects"]}


async def test_un_lot_conforme_pose_une_ligne_par_objet_sous_sa_forme_transformee(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 1 : la clé extraite, le modèle transformé, l'empreinte, les deux dates."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        recu = await depot.depose(LOT)

        assert recu.status_code == 201, recu.text
        rapport = recu.json()["report"]
        assert (rapport["received"], rapport["written"]) == (2, 2)
        assert (rapport["unchanged"], rapport["rejected"]) == (0, 0)
        assert recu.json()["state"] == STATE_PROCESSED
        lignes = await depot.lignes()
        assert set(lignes) == {M1, M2}
        ligne = lignes[M1]
        assert json.loads(ligne["objet"]) == _transforme("M-1", "Gare du Nord", "Paris", 3)
        assert ligne["origine"] == IMPORT_ORIGIN
        # Les deux dates partent égales : l'objet est né de cet import.
        assert ligne["vu_le"] == ligne["modifie_le"] == depot.horloge.instant
        # La version du modèle contre laquelle l'objet a été validé : c'est elle qui rend
        # un résultat contesté reproductible.
        assert ligne["version_modele"] == 1
        assert len(ligne["empreinte"]) == 32


async def test_les_colonnes_projetees_sont_DERIVEES_par_la_base(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 5. `attgenerated = 's'` est la preuve que rien d'applicatif ne les écrit :
    PostgreSQL REFUSE une écriture vers une colonne générée. La valeur seule ne dirait
    pas d'où elle vient."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        await depot.depose(LOT)

        lignes = await depot.lignes()
        assert lignes[M1][PROJETEE] == "Paris"
        assert lignes[M2][PROJETEE] == "Lyon"
        genere = await stack.pool.fetchval(
            "SELECT a.attgenerated FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = $1 AND c.relname = $2 AND a.attname = $3",
            SCHEMA,
            TABLE,
            PROJETEE,
        )
        # `b"s"` et non `"s"` : `attgenerated` est du type catalogue `"char"`, qu'asyncpg
        # rend en OCTETS. Mesuré le 03/11/2026 — comparer à la chaîne échoue sur une
        # colonne pourtant bien générée, et le test aurait accusé le DDL.
        assert genere == b"s"


async def test_un_reimport_a_l_identique_n_avance_QUE_la_date_de_derniere_vue(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 2, et la correction du 26/10/2026 au ticket. L'empreinte doit rester LA
    MÊME : la réécrire à l'identique serait invisible ici, mais pas sur l'horodatage des
    tuples — c'est pourquoi le corps est comparé à son texte d'avant, caractère pour
    caractère."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.depose(LOT)
        avant = await depot.lignes()

        rejoue = await depot.depose(LOT)

        assert rejoue.status_code == 201, rejoue.text
        rapport = rejoue.json()["report"]
        assert (rapport["written"], rapport["unchanged"]) == (0, 2)
        apres = await depot.lignes()
        for cle in (M1, M2):
            assert apres[cle]["objet"] == avant[cle]["objet"]
            assert apres[cle]["empreinte"] == avant[cle]["empreinte"]
            # La date de l'historique n'a pas bougé…
            assert apres[cle]["modifie_le"] == avant[cle]["modifie_le"]
            # … et celle que le balayage lit a avancé. Sans elle, un objet réimporté à
            # chaque fois serait indiscernable d'un objet oublié, et le balayage finirait
            # par le sortir alors que sa source l'envoie toujours.
            assert apres[cle]["vu_le"] == depot.horloge.instant
            assert apres[cle]["vu_le"] > avant[cle]["vu_le"]


async def test_un_objet_modifie_est_SEUL_a_voir_son_corps_et_sa_date_de_modification_bouger(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 3 : le delta est par LIGNE, pas par lot."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.depose(LOT)
        avant = await depot.lignes()

        modifie = [_objet("M-1", "Gare du Nord", "Paris", 9), LOT[1]]
        recu = await depot.depose(modifie)

        rapport = recu.json()["report"]
        assert (rapport["written"], rapport["unchanged"]) == (1, 1)
        apres = await depot.lignes()
        assert json.loads(apres[M1]["objet"])["Postes"] == 9
        assert apres[M1]["modifie_le"] == depot.horloge.instant
        assert apres[M1]["empreinte"] != avant[M1]["empreinte"]
        # L'autre ligne du même lot est intacte, sa date de dernière vue exceptée.
        assert apres[M2]["objet"] == avant[M2]["objet"]
        assert apres[M2]["modifie_le"] == avant[M2]["modifie_le"]
        assert apres[M2]["vu_le"] == depot.horloge.instant


async def test_une_variation_NON_SIGNIFICATIVE_de_la_source_ne_reecrit_rien(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 4, et c'est lui qui prouve que l'empreinte porte sur le TRANSFORMÉ.

    Deux variations à la fois, parce que ce sont celles qu'une source réelle produit sans
    rien changer : les clés JSON dans un autre ordre, et un champ d'émission que le
    template ne lit pas. Hacher le message source ferait tout réécrire à chaque remise.
    """
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.depose(LOT)
        avant = await depot.lignes()

        remue = [
            {"emis_le": "T1", "postes": 3, "ville": "Paris", "nom": "Gare du Nord", "code": "M-1"},
            {"emis_le": "T1", "postes": 7, "ville": "Lyon", "nom": "Part-Dieu", "code": "M-2"},
        ]
        recu = await depot.depose(remue)

        rapport = recu.json()["report"]
        assert (rapport["written"], rapport["unchanged"]) == (0, 2)
        apres = await depot.lignes()
        for cle in (M1, M2):
            assert apres[cle]["empreinte"] == avant[cle]["empreinte"]
            assert apres[cle]["modifie_le"] == avant[cle]["modifie_le"]
            assert apres[cle]["vu_le"] == depot.horloge.instant


async def test_un_objet_inconnu_dans_un_reimport_est_cree(blank_db: str, tmp_path: Path) -> None:
    """Critère 6 : les anciens sont revus, le nouveau naît."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.depose(LOT)
        avant = await depot.lignes()

        recu = await depot.depose([*LOT, _objet("M-3", "Saint-Charles", "Marseille", 2)])

        rapport = recu.json()["report"]
        assert (rapport["received"], rapport["written"], rapport["unchanged"]) == (3, 1, 2)
        apres = await depot.lignes()
        assert set(apres) == {M1, M2, M3}
        assert apres[M3]["vu_le"] == apres[M3]["modifie_le"] == depot.horloge.instant
        assert apres[M1]["modifie_le"] == avant[M1]["modifie_le"]


async def test_un_import_sur_la_cle_d_un_objet_MANUEL_le_refuse_et_traite_le_reste(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 7. La ligne manuelle ne doit pas bouger du tout — `vu_le` COMPRIS : c'est
    ce qui l'exclut du balayage, puisque aucun import ne la réécrira jamais."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        pose_le = DEBUT - timedelta(days=30)
        await depot.pose_manuel(M1, _transforme("M-1", "Saisi à la main", "Paris", 1), pose_le)

        recu = await depot.depose(LOT)

        assert recu.status_code == 201, recu.text
        sorts = _sorts(recu)
        assert (sorts[0]["outcome"], sorts[0]["reason"]) == (REJECTED, REJECT_MANUAL)
        assert sorts[0]["key"] == M1
        assert sorts[1]["outcome"] == WRITTEN
        lignes = await depot.lignes()
        assert json.loads(lignes[M1]["objet"])["Libelle"] == "Saisi à la main"
        assert lignes[M1]["origine"] == MANUAL_ORIGIN
        assert lignes[M1]["vu_le"] == lignes[M1]["modifie_le"] == pose_le
        assert lignes[M2]["origine"] == IMPORT_ORIGIN


async def test_un_lot_ENTIEREMENT_rejete_rend_422_et_ne_touche_AUCUNE_ligne(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 12. Éprouvé sur une table DÉJÀ peuplée : sur une table vide, « aucune
    ligne modifiée » serait vrai sans rien prouver."""
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        await depot.depose(LOT)
        avant = await depot.lignes()

        # `nom` absent : le template rend `Libelle: null`, que le modèle exige en chaîne.
        fautifs = [
            {"code": "M-1", "ville": "Paris", "postes": 3},
            {"code": "M-9", "ville": "Nice", "postes": 1},
        ]
        refus = await depot.depose(fautifs)

        assert refus.status_code == 422, refus.text
        assert refus.json()["state"] == STATE_FAILED
        assert refus.json()["report"]["rejected"] == 2
        assert {o["reason"] for o in _sorts(refus).values()} == {REJECT_MODEL}
        apres = await depot.lignes()
        assert set(apres) == {M1, M2}
        for cle in (M1, M2):
            # `vu_le` compris : le lot n'a pas « revu » ces objets, il a échoué.
            assert apres[cle]["vu_le"] == avant[cle]["vu_le"]
            assert apres[cle]["modifie_le"] == avant[cle]["modifie_le"]
        # Le dépôt reste en base — il est arrivé — mais aucun event d'écriture d'objet
        # n'a été écrit pour lui.
        ecrits = await stack.pool.fetchval(
            "SELECT count(*) FROM events WHERE type = $1", OBJECT_WRITTEN_EVENT
        )
        assert ecrits == 2


async def test_le_compte_rendu_porte_les_comptes_et_le_MOTIF_de_chaque_rejet(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 15, sur un lot où les trois issues cohabitent : c'est la seule forme qui
    discrimine, un lot homogène laissant passer un compte calculé sur le lot entier."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        await depot.depose(LOT)

        melange = [
            LOT[0],
            _objet("M-2", "Part-Dieu rénovée", "Lyon", 7),
            {"code": "M-4", "ville": "Lille", "postes": 1},
        ]
        recu = await depot.depose(melange)

        rapport = recu.json()["report"]
        assert rapport["received"] == 3
        assert (rapport["written"], rapport["unchanged"], rapport["rejected"]) == (1, 1, 1)
        assert rapport["anomalies"] == []
        sorts = _sorts(recu)
        assert sorts[0]["outcome"] == UNCHANGED
        assert sorts[1]["outcome"] == WRITTEN
        assert (sorts[2]["outcome"], sorts[2]["reason"]) == (REJECTED, REJECT_MODEL)
        # Le chemin de l'écart, pour corriger le template sans appel exploratoire.
        assert "Libelle" in sorts[2]["detail"]
        # La clé est nulle sur un rejet d'avant l'extraction : le rang est alors la seule
        # prise de l'appelant pour retrouver lequel de ses objets est en cause.
        assert sorts[2]["key"] is None


async def test_un_rejeu_rend_le_MEME_compte_rendu_sans_rien_reecrire(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 13. Et l'horloge N'AVANCE PAS au rejeu : si le rejeu réécrivait, il
    écrirait le même instant, et la comparaison des dates ne dirait rien. L'horloge est
    donc avancée AVANT de rejouer, pour qu'une écriture laisse une trace visible."""
    async with _ouvre(blank_db, tmp_path) as (_, depot):
        premier = await depot.depose(LOT, idempotence="lot-du-3-novembre")
        avant = await depot.lignes()

        second = await depot.depose(LOT, idempotence="lot-du-3-novembre")

        assert second.status_code == 200, second.text
        assert second.json()["replayed"] is True
        assert second.json()["id"] == premier.json()["id"]
        assert second.json()["report"] == premier.json()["report"]
        apres = await depot.lignes()
        for cle in (M1, M2):
            # Aucune des deux dates n'a bougé : le rejeu n'a même pas « revu » les objets.
            assert apres[cle]["vu_le"] == avant[cle]["vu_le"]
            assert apres[cle]["modifie_le"] == avant[cle]["modifie_le"]


async def test_une_interruption_du_traitement_ne_laisse_NI_lot_NI_ligne(
    blank_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Critère 14, premier volet : la transaction unique.

    L'interruption est provoquée APRÈS la persistance du lot et pendant le traitement —
    c'est le seul endroit où les deux gestes pourraient se désolidariser. Rien ne doit
    rester : ni la ligne d'ingestion, ni un objet écrit avant l'arrêt. Puis le même dépôt
    rejoué repart de zéro, sans doublon.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, depot):

        def _interrompt(*_: object, **__: object) -> Any:
            raise RuntimeError("interruption en cours de traitement")

        monkeypatch.setattr(
            "environnement.ingestion.service.resolve_process", _interrompt, raising=True
        )
        with pytest.raises(RuntimeError):
            await depot.depose(LOT)

        assert await stack.pool.fetchval("SELECT count(*) FROM ingestions") == 0
        assert await depot.lignes() == {}

        monkeypatch.undo()
        repris = await depot.depose(LOT)

        assert repris.status_code == 201, repris.text
        assert repris.json()["report"]["written"] == 2
        assert set(await depot.lignes()) == {M1, M2}


async def test_un_lot_recu_mais_JAMAIS_traite_est_repris_au_rejeu(
    blank_db: str, tmp_path: Path
) -> None:
    """Critère 14, second volet : l'état « reçu sans compte-rendu » REPREND le traitement.

    Cet état est fabriqué ici, et c'est délibéré : la transaction unique fait qu'il ne
    peut plus naître d'un arrêt du service. Il reste celui des dépôts enregistrés avant
    que ce ticket ne traite — et c'est précisément ce que la branche de reprise sert. Un
    rejeu qui rendrait un compte-rendu vide ferait croire au partenaire que son lot n'a
    rien écrit.

    Le lot traité est celui de la BASE, pas celui du corps rejoué : c'est la trace du
    premier dépôt qui fait foi. Le corps du rejeu est donc volontairement différent.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        premier = await depot.depose(LOT, idempotence="lot-interrompu")
        await stack.pool.execute(
            "UPDATE ingestions SET state = 'recu', report = NULL WHERE id = $1",
            premier.json()["id"],
        )
        await stack.pool.execute(f"DELETE FROM {SCHEMA}.{TABLE}")  # noqa: S608

        autre = [_objet("M-9", "Autre chose", "Nice", 1)]
        repris = await depot.depose(autre, idempotence="lot-interrompu")

        assert repris.status_code == 201, repris.text
        assert repris.json()["id"] == premier.json()["id"]
        assert repris.json()["state"] == STATE_PROCESSED
        assert repris.json()["report"]["written"] == 2
        # Les objets du PREMIER dépôt, et pas celui du corps rejoué.
        assert set(await depot.lignes()) == {M1, M2}


async def test_chaque_objet_ECRIT_laisse_son_event_et_un_objet_inchange_AUCUN(
    blank_db: str, tmp_path: Path
) -> None:
    """La décision de Gael du 03/11/2026 — un event par objet écrit — mesurée sur la base.

    Un objet inchangé n'en produit aucun : il n'y a pas eu de modification, et c'est le
    DELTA constaté qui parle. Ce qui se mesure ici et pas sur une doublure, c'est que
    l'event est dans la MÊME transaction que l'écriture.
    """
    async with _ouvre(blank_db, tmp_path) as (stack, depot):
        await depot.depose(LOT)

        await depot.depose([LOT[0], _objet("M-2", "Part-Dieu rénovée", "Lyon", 7)])

        rows = await stack.pool.fetch(
            "SELECT e.properties::text AS p, o.object_id FROM events e"
            " JOIN event_objects o ON o.event_id = e.id AND o.written_at = e.written_at"
            " WHERE e.type = $1 ORDER BY e.written_at, o.object_id",
            OBJECT_WRITTEN_EVENT,
        )
        # Deux créations, puis la seule mise à jour du second dépôt.
        assert [row["object_id"] for row in rows] == [M1, M2, M2]
        assert [json.loads(row["p"])["created"] for row in rows] == [True, True, False]
