"""La table temporaire d'un import : posée vide, remplie par COPY, relue sans les corps.

Sur une doublure qui ENREGISTRE ce qui lui est demandé : ce qui doit être éprouvé ici est
la forme des gestes — l'ordre « ôter puis poser », les colonnes de la copie, et le fait que
la fenêtre de relecture ne demande PAS les objets. La table temporaire elle-même est
éprouvée sur PostgreSQL par la campagne d'intégration.
"""

from __future__ import annotations

from typing import Any

from environnement.ingestion.preparation import PreparedObject
from environnement.ingestion.staging import (
    PREPARED_TABLE,
    db_close_prepared,
    db_copy_prepared,
    db_duplicate_keys,
    db_open_prepared,
    db_prepared_window,
)


class _Db:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.instructions: list[str] = []
        self.copies: list[tuple[str, list[Any], tuple[str, ...]]] = []
        self.requetes: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.instructions.append(" ".join(query.split()))
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.requetes.append((" ".join(query.split()), args))
        return self.rows

    async def copy_records_to_table(self, table_name: str, *, records: Any, columns: Any) -> str:
        self.copies.append((table_name, list(records), tuple(columns)))
        return "COPY"


def _item(position: int, cle: str = "S-1", reason: str | None = None) -> PreparedObject:
    if reason is not None:
        return PreparedObject(position, None, None, None, reason, "détail")
    return PreparedObject(position, cle, {"Code": cle}, b"\x02" * 32)


async def test_l_aire_est_OTEE_avant_d_etre_posee() -> None:
    """L'ordre est la garde : la connexion vient d'un pool, et un reliquat de l'import
    précédent ferait écrire les items d'un autre document."""
    db = _Db()

    await db_open_prepared(db)

    assert db.instructions[0].startswith("DROP TABLE IF EXISTS")
    assert "CREATE TEMP TABLE" in db.instructions[1]


async def test_l_aire_posee_est_TEMPORAIRE_et_porte_ses_invariants() -> None:
    db = _Db()

    await db_open_prepared(db)

    creation = db.instructions[1]
    assert f"CREATE TEMP TABLE {PREPARED_TABLE}" in creation
    # Un item « à écrire » sans objet, sans empreinte ou sans clé ne doit pas exister.
    assert "CHECK ((outcome = 'a_ecrire') = (objet IS NOT NULL" in creation


async def test_la_fermeture_est_REJOUABLE() -> None:
    """Un import abandonné n'en laisse pas, et l'ôter deux fois n'est pas un incident."""
    db = _Db()

    await db_close_prepared(db)
    await db_close_prepared(db)

    assert db.instructions == ["DROP TABLE IF EXISTS pg_temp.ingestion_prepared"] * 2


async def test_la_copie_en_masse_envoie_les_sept_colonnes_dans_l_ordre() -> None:
    db = _Db()

    await db_copy_prepared(db, [_item(0, "S-1"), _item(1, reason="modele_non_respecte")])

    table, records, colonnes = db.copies[0]
    assert table == PREPARED_TABLE
    assert colonnes == ("position", "outcome", "cle", "objet", "empreinte", "reason", "detail")
    assert [ligne[1] for ligne in records] == ["a_ecrire", "rejete"]
    # L'objet part SÉRIALISÉ : une colonne jsonb ne prend pas un dictionnaire Python.
    assert records[0][3] == '{"Code": "S-1"}'
    # Un rejet n'a ni objet ni empreinte, et porte son motif.
    assert (records[1][3], records[1][4], records[1][5]) == (None, None, "modele_non_respecte")


async def test_une_copie_VIDE_n_ecrit_rien() -> None:
    """Le dernier paquet d'un document est vide : il ne doit pas ouvrir de COPY."""
    db = _Db()

    await db_copy_prepared(db, [])

    assert db.copies == []


async def test_la_fenetre_ne_demande_PAS_les_objets() -> None:
    """C'est tout le dispositif : les corps vont de l'aire à la table finale SANS remonter.

    Les relire ici ferait voyager deux fois cinquante mille documents pour les renvoyer
    aussitôt — et rendrait en mémoire ce que la lecture en flux avait évité de garder.
    """
    db = _Db()

    await db_prepared_window(db, after=99, limit=100)

    requete, arguments = db.requetes[0]
    assert "objet" not in requete and "empreinte" not in requete
    assert arguments == (99, 100)


async def test_la_fenetre_rend_le_sort_et_le_motif_de_chaque_rang() -> None:
    db = _Db(
        [
            {"position": 3, "outcome": "a_ecrire", "cle": "S-1", "reason": None, "detail": None},
            {
                "position": 4,
                "outcome": "rejete",
                "cle": None,
                "reason": "modele_non_respecte",
                "detail": "$.Code",
            },
        ]
    )

    fenetre = await db_prepared_window(db, after=2, limit=10)

    assert [(ligne.position, ligne.writable) for ligne in fenetre] == [(3, True), (4, False)]
    assert (fenetre[1].reason, fenetre[1].detail) == ("modele_non_respecte", "$.Code")


async def test_les_cles_en_double_sont_cherchees_en_SQL_et_BORNEES() -> None:
    """Un index de cinquante mille clés en mémoire aurait annulé la lecture en flux."""
    db = _Db([{"cle": "S-1"}, {"cle": "S-2"}])

    cles = await db_duplicate_keys(db, limit=200)

    requete, arguments = db.requetes[0]
    assert "GROUP BY cle HAVING count(*) > 1" in requete
    assert arguments == ("a_ecrire", 200) and cles == ["S-1", "S-2"]
