"""La POSE et la LEVÉE de la marque d'absence : ce que les instructions disent.

Ce qui est éprouvé ici est NOTRE part : les clauses que la sélection porte, le repli devant
un item sans clé, et la lecture du nombre de lignes touchées. Que PostgreSQL applique bien
ces clauses est mesuré par la campagne d'intégration — une doublure qui rejouerait un
`UPDATE … WHERE` ne prouverait que la doublure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from environnement.ingestion.absence import clear_statement, db_mark_absent, mark_statement
from environnement.storages.model import StorageTable

DEBUT = datetime(2026, 11, 9, 8, tzinfo=UTC)
TABLE = StorageTable(
    storage="sites",
    label="Sites",
    schema="pudo",
    table="sites",
    model="pudo/site",
    projections=(),
    indexes=(),
    keys=("$.Code",),
)


class _Db:
    """Doublure : elle rend le compte d'items sans clé qu'on lui donne, puis l'étiquette."""

    def __init__(self, *, sans_cle: int = 0, tag: str = "UPDATE 3") -> None:
        self.sans_cle, self.tag = sans_cle, tag
        self.instructions: list[str] = []
        self.arguments: list[tuple[Any, ...]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        return self.sans_cle

    async def execute(self, query: str, *args: Any) -> str:
        self.instructions.append(query)
        self.arguments.append(args)
        return self.tag


class TestLInstruction:
    def test_les_identites_sont_citees_et_jamais_concatenees(self) -> None:
        sql = mark_statement(TABLE)

        assert 'UPDATE "pudo"."sites"' in sql
        assert '"absent_depuis" = $1' in sql

    def test_une_marque_deja_posee_n_est_jamais_retouchee(self) -> None:
        """La décision de Gael : « on ne retouche pas l'item déjà marqué missing dans le
        précédent import ». C'est cette date qui donne « absent depuis N jours »."""
        assert '"absent_depuis" IS NULL' in mark_statement(TABLE)

    def test_un_item_d_origine_MANUELLE_est_marque_comme_un_autre(self) -> None:
        """Arbitrage de Gael du 09/11/2026, contre ce qui avait d'abord été écrit : « si je
        fais un full et que le point n'y est pas je le marque absent ».

        La marque est un CONSTAT sur ce que la source porte, pas un jugement sur l'origine
        de l'objet. Une clause sur l'origine aurait rendu le constat impossible à faire
        pour une ligne manuelle que la source ignore — alors que c'est précisément celle
        qu'il faut rendre visible. Épargner le manuel, si on le veut, revient aux règles
        de nettoyage.
        """
        assert "origine" not in mark_statement(TABLE)

    def test_la_frontiere_est_la_date_de_vue_et_non_celle_de_modification(self) -> None:
        """`vu_le` avance sur toute clé qu'un import porte, même sans changement ;
        `modifie_le` non, et s'en servir aurait marqué tout ce qui n'a pas changé."""
        sql = mark_statement(TABLE)

        assert "c.vu_le < $2" in sql
        assert "modifie_le" not in sql

    def test_les_items_lus_par_cet_import_sont_protegES_par_l_aire_de_preparation(
        self,
    ) -> None:
        """Y compris ceux que le modèle a rejetés : la source en a parlé."""
        sql = mark_statement(TABLE)

        assert "NOT EXISTS" in sql
        assert "pg_temp.ingestion_prepared p WHERE p.cle = c.cle" in sql

    def test_la_ligne_manuelle_que_le_fichier_PORTE_est_epargnee_par_l_aire(self) -> None:
        """Sans clause d'origine, c'est la seule chose qui la protège : la fusion refuse de
        l'écraser, donc son `vu_le` n'avance pas, et elle serait candidate à chaque import.
        """
        sql = mark_statement(TABLE)

        assert "NOT EXISTS" in sql
        assert "c.vu_le < $2" in sql

    def test_rien_d_autre_que_la_marque_n_est_ecrit(self) -> None:
        """Ni l'objet, ni l'empreinte, ni `modifie_le` : une marque n'est pas une
        modification venue de la source, et réécrire l'objet referait son stockage TOAST."""
        sql = mark_statement(TABLE)

        assert sql.count("SET") == 1
        for jamais in ("objet", "empreinte", "version_modele"):
            assert f"{jamais} =" not in sql


class TestLaLevee:
    """La levée depuis l'aire de préparation : ce que la fusion ne peut pas couvrir."""

    def test_la_levee_porte_sur_les_cles_que_le_document_A_portees(self) -> None:
        """L'exact inverse de la pose, et sur la même source — l'aire porte une ligne par
        item LU, donc elle couvre aussi l'item rejeté, pour lequel rien n'a été écrit."""
        sql = clear_statement(TABLE)

        assert 'UPDATE "pudo"."sites"' in sql
        assert '"absent_depuis" = NULL' in sql
        assert "EXISTS" in sql and "NOT EXISTS" not in sql
        assert "pg_temp.ingestion_prepared p WHERE p.cle = c.cle" in sql

    def test_la_levee_ne_regarde_pas_l_origine_ni_la_date_de_vue(self) -> None:
        """C'est tout son objet : la fusion lève déjà ce qu'elle écrit, et ce qui reste à
        lever est justement ce qu'elle n'écrit pas — la ligne manuelle, l'item rejeté."""
        sql = clear_statement(TABLE)

        assert "origine" not in sql
        assert "vu_le" not in sql

    def test_la_levee_ne_touche_que_des_lignes_DEJA_marquees(self) -> None:
        """Toucher les autres compterait des lignes sans objet, et ferait écrire la table
        entière à chaque import."""
        assert '"absent_depuis" IS NOT NULL' in clear_statement(TABLE)


class TestLaPose:
    @pytest.mark.asyncio
    async def test_la_date_posee_et_la_frontiere_sont_le_MEME_instant(self) -> None:
        """Deux instants différents auraient fait répondre « absent depuis » et « vu
        avant » à deux questions qu'on croit identiques."""
        db = _Db()

        await db_mark_absent(db, TABLE, started_at=DEBUT)

        # La levée ne prend aucun paramètre : elle lit l'aire, qui est celle de cet import.
        assert db.arguments == [(), (DEBUT, DEBUT)]

    @pytest.mark.asyncio
    async def test_le_nombre_de_marques_est_MESURE_sur_l_etiquette_de_la_base(self) -> None:
        assert await db_mark_absent(_Db(tag="UPDATE 12"), TABLE, started_at=DEBUT) == 12

    @pytest.mark.asyncio
    async def test_un_import_qui_ne_marque_rien_rend_zero_et_non_une_absence(self) -> None:
        """Zéro et `None` ne disent pas la même chose : l'un est un import complet qui
        n'avait rien à marquer, l'autre un marquage qu'on a refusé de faire."""
        assert await db_mark_absent(_Db(tag="UPDATE 0"), TABLE, started_at=DEBUT) == 0

    @pytest.mark.asyncio
    async def test_un_item_SANS_CLE_lu_par_l_import_abandonne_tout_le_marquage(self) -> None:
        """Repli volontaire : un tel item n'est protégé par rien — l'aire le porte, mais
        sans clé —, et la ligne qu'il désignait serait marquée alors que le document en
        parlait. Une marque de trop devient une suppression ; une marque en retard se
        rattrape au prochain import complet."""
        db = _Db(sans_cle=1)

        assert await db_mark_absent(db, TABLE, started_at=DEBUT) is None
        # La LEVÉE a bien eu lieu : elle ne va que dans le sens qui épargne un item, et un
        # item sans clé n'enlève rien à ce que les items qui en ont une prouvent. Y
        # renoncer aussi n'aurait protégé personne et aurait laissé sur place des marques
        # que la source contredit.
        assert db.instructions == [clear_statement(TABLE)]
