"""L'application de l'aire à la table du storage : fenêtres, instructions, transactions.

Ce qui est éprouvé ici est l'ORCHESTRATION — combien de fenêtres sont lues, combien
d'instructions de fusion elles engendrent, combien de transactions s'ouvrent, et ce que le
compte-rendu dit. La sémantique SQL est celle de PostgreSQL, et la campagne d'intégration
la mesure ; la doublure, elle, répond au CONTRAT des requêtes.

Les deux réglages ne doivent pas se confondre, et c'est le point de la plupart de ces
tests : `lot_ecriture` dit tous les combien on VALIDE, `MERGE_WINDOW` borne la taille d'une
INSTRUCTION — parce que son coût par item croît avec sa taille (mesuré le 06/11/2026).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from miles_socle.events.model import EventAuthor

from environnement.event_types import code_event_catalog
from environnement.ingestion.applystaging import ApplyPlan, resolve_apply
from environnement.ingestion.conformance import model_validator
from environnement.ingestion.keys import key_rule
from environnement.ingestion.outcome import REJECTED, UNCHANGED, WRITTEN
from environnement.ingestion.staging import STAGED_REJECTED, STAGED_TO_WRITE
from environnement.ingestion.store_merge import MERGE_WINDOW
from environnement.ingestion.writeback import Prepared, Processing
from environnement.storages.model import StorageTable

NOW = datetime(2026, 11, 6, 12, tzinfo=UTC)
TABLE = StorageTable(
    storage="sites",
    label="Sites",
    schema="public",
    table="sites",
    model="pudo/site",
    projections=(),
    indexes=(),
    keys=("$.Code",),
)


class _Bloc:
    """La transaction d'asyncpg : imbriquée, elle devient un POINT DE SAUVEGARDE.

    La doublure fait la même distinction, parce que le journal en ouvre un par fenêtre
    pour rattraper une partition manquante : compter tous les blocs ferait dire « quatre
    transactions » là où il y en a une et trois points de sauvegarde.
    """

    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    async def __aenter__(self) -> None:
        self.conn.profondeur += 1
        if self.conn.profondeur == 1:
            self.conn.transactions += 1
        else:
            self.conn.sauvegardes += 1

    async def __aexit__(self, *_: object) -> None:
        self.conn.profondeur -= 1


class _Conn:
    """Doublure de connexion : elle répond au contrat des trois requêtes de l'aire.

    `deja` porte l'état de la table cible, comme la CTE `avant` le lit : rien pour une
    création, « import » plus une empreinte pour une mise à jour.
    """

    def __init__(self, rangs: list[tuple[int, bool]], deja: dict[str, Any] | None = None) -> None:
        self.rangs = rangs
        self.deja = deja or {}
        self.fenetres: list[tuple[int, int]] = []
        self.fusions: list[tuple[int, int]] = []
        self.events: list[str] = []
        self.transactions = 0
        self.sauvegardes = 0
        self.profondeur = 0
        self.sequences = 0

    def is_in_transaction(self) -> bool:
        return True

    def transaction(self) -> Any:
        return _Bloc(self)

    async def execute(self, query: str, *args: Any) -> str:
        if "INTO events" in query:
            self.events.extend(args[1])
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        if "event_object_sequences" in query:
            self.sequences += 1
            return [
                {"object_kind": k, "object_id": i, "last_sequence": 1}
                for k, i in zip(args[0], args[1], strict=True)
            ]
        if "GROUP BY cle HAVING" in query:
            return []
        # La fusion AVANT la fenêtre : son fragment de source nomme la même table, et
        # tester la fenêtre d'abord lui ferait prendre l'instant pour un rang.
        if query.lstrip().startswith("WITH candidats"):
            return self._fusion(args[3], args[4])
        if "ingestion_prepared" in query:
            return self._fenetre(args[0], args[1])
        raise AssertionError(f"requête inattendue : {query[:50]}")

    def _fenetre(self, after: int, limite: int) -> list[Any]:
        suite = [(rang, ecrivable) for rang, ecrivable in self.rangs if rang > after][:limite]
        self.fenetres.append((after, limite))
        return [
            {
                "position": rang,
                "outcome": STAGED_TO_WRITE if ecrivable else STAGED_REJECTED,
                "cle": f"S-{rang}" if ecrivable else None,
                "reason": None if ecrivable else "modele_non_respecte",
                "detail": None if ecrivable else "$.Code",
            }
            for rang, ecrivable in suite
        ]

    def _fusion(self, after: int, through: int) -> list[Any]:
        self.fusions.append((after, through))
        rendus = []
        for rang, ecrivable in self.rangs:
            if not ecrivable or not (after < rang <= through):
                continue
            cle = f"S-{rang}"
            empreinte_avant = self.deja.get(cle)
            self.deja[cle] = b"\x01" * 32
            rendus.append(
                {
                    "position": rang,
                    "cle": cle,
                    "posee": True,
                    "origine_avant": None if empreinte_avant is None else "import",
                    "identique": empreinte_avant == b"\x01" * 32,
                    "generations": 1,
                }
            )
        return rendus


def _processing(conn: _Conn) -> Processing:
    return Processing(
        db=conn,
        catalog=code_event_catalog(),
        now=lambda: NOW,
        budget=100_000,
        author=EventAuthor("apikey", "k-1"),
        ingestion_id="a" * 32,
        model_version=7,
    )


def _plan(**surcharges: Any) -> ApplyPlan:
    forme: dict[str, Any] = {
        "unified": False,
        "write_batch": 100,
        "seconds": 60.0,
        "detail_cap": 200,
    }
    forme.update(surcharges)
    return ApplyPlan(**forme)


def _prepared() -> Prepared:
    return Prepared(
        table=TABLE, validator=model_validator({}), chain=None, keys=key_rule(TABLE.keys)
    )


async def test_un_lot_d_ecriture_PLUS_GRAND_que_la_fenetre_ne_fait_pas_une_instruction() -> None:
    """La séparation des deux réglages, qui est tout l'objet de `MERGE_WINDOW`.

    `lot_ecriture` de 500 : UNE transaction pour cinq cents items — c'est ce qu'il
    promet —, mais CINQ instructions de fusion, parce que le coût par item d'une
    instruction croît avec sa taille.
    """
    conn = _Conn([(rang, True) for rang in range(500)])

    rapport = await resolve_apply(conn, _processing(conn), _prepared(), _plan(write_batch=500))

    assert conn.fenetres == [(-1, 500), (499, 500)]
    assert len(conn.fusions) == 5
    assert [borne - depart for depart, borne in conn.fusions] == [MERGE_WINDOW] * 5
    assert rapport.written == 500 and rapport.received == 500


async def test_les_tranches_de_fusion_se_SUIVENT_sans_trou_ni_recouvrement() -> None:
    """Un trou perdrait des objets, un recouvrement les écrirait deux fois."""
    conn = _Conn([(rang, True) for rang in range(250)])

    await resolve_apply(conn, _processing(conn), _prepared(), _plan(write_batch=250))

    assert conn.fusions == [(-1, 99), (99, 199), (199, 249)]


async def test_une_transaction_PAR_LOT_sans_transaction_unifiee() -> None:
    """Critère 8 : un document interrompu laisse écrits les items lus avant l'incident."""
    conn = _Conn([(rang, True) for rang in range(250)])

    await resolve_apply(conn, _processing(conn), _prepared(), _plan(write_batch=100))

    # Trois lots de cent, donc trois transactions — et autant d'instructions de fusion.
    assert conn.transactions == 3 and len(conn.fusions) == 3
    # Le journal ouvre son point de sauvegarde DANS chacune, jamais à côté : aucun fait
    # observable sans sa trace, et jamais deux transactions.
    assert conn.sauvegardes == 3


async def test_une_SEULE_transaction_quand_elle_est_unifiee() -> None:
    """Critère 7 : tout ou rien, même sur une interruption au milieu."""
    conn = _Conn([(rang, True) for rang in range(250)])

    await resolve_apply(conn, _processing(conn), _prepared(), _plan(unified=True, write_batch=100))

    assert conn.transactions == 1 and len(conn.fusions) == 3
    assert conn.sauvegardes == 3


async def test_les_events_d_une_fenetre_partent_en_UN_appel() -> None:
    """Un event par objet écrit, et une seule instruction par fenêtre pour les porter."""
    conn = _Conn([(rang, True) for rang in range(100)])

    await resolve_apply(conn, _processing(conn), _prepared(), _plan(write_batch=100))

    assert len(conn.events) == 100
    # Une réservation de numéros pour toute la fenêtre, pas une par objet.
    assert conn.sequences == 1


async def test_un_objet_INCHANGE_ne_produit_aucun_event() -> None:
    """C'est le DELTA constaté qui parle, jamais le fait que le code ait tourné."""
    conn = _Conn([(0, True)], deja={"S-0": b"\x01" * 32})

    rapport = await resolve_apply(conn, _processing(conn), _prepared(), _plan())

    assert rapport.unchanged == 1 and rapport.written == 0
    assert conn.events == [] and conn.sequences == 0


async def test_les_rejets_sont_comptes_depuis_la_fenetre_sans_toucher_la_base() -> None:
    """Décidés à la préparation : les envoyer à la fusion écrirait une ligne nulle."""
    conn = _Conn([(0, True), (1, False), (2, True)])

    rapport = await resolve_apply(conn, _processing(conn), _prepared(), _plan())

    assert (rapport.written, rapport.rejected, rapport.received) == (2, 1, 3)
    assert [o.outcome for o in rapport.objects] == [REJECTED]
    assert rapport.objects[0].reason == "modele_non_respecte"


async def test_le_compte_rendu_garde_les_trois_comptes_dans_l_ordre_des_rangs() -> None:
    conn = _Conn([(0, True), (1, True)], deja={"S-1": b"\x01" * 32})

    rapport = await resolve_apply(conn, _processing(conn), _prepared(), _plan())

    assert rapport.tallies == {WRITTEN: 1, UNCHANGED: 1, REJECTED: 0}
