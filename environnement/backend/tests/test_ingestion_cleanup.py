"""Les règles de NETTOYAGE : ce que les instructions disent, et ce que le balayage fait.

Ce qui est éprouvé ici est NOTRE part : les clauses que chaque règle porte, le seuil qui
se déplace, le refus en bloc d'un storage dont une règle n'est plus évaluable, et le
balayage par fenêtres. Que PostgreSQL applique bien ces clauses sur de vraies lignes — et
que l'ordre lexicographique d'un ISO-8601 décide juste — est mesuré par la campagne
d'intégration : une doublure qui rejouerait un `DELETE … WHERE` ne prouverait que la
doublure, et le prix d'une erreur ici est une suppression.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from miles_socle.events.model import EventAuthor, EventTypeCatalog
from miles_socle.parametrage.sources import Entry, EntryModes, SourceDoc

from environnement.ingestion.cleanup import (
    ISO_DATE_RE,
    KIND_EXPIRY,
    KIND_MISSING,
    OBJECT_REMOVED_EVENT,
    REMOVAL_WINDOW,
    count_statement,
    db_remove_designated,
    expiry_rule,
    missing_rule,
    page_statement,
    removable,
    rule_id,
    rules_of,
    scan_statement,
    threshold,
)
from environnement.ingestion.writeback import Processing
from environnement.storages.model import ExpiryRule, Projection, StorageTable

MAINTENANT = datetime(2026, 11, 9, 8, tzinfo=UTC)
FIN = ExpiryRule("$.FinActivite", "fin_activite", 10)
TABLE = StorageTable(
    storage="magasins",
    label="Magasins",
    schema="pudo",
    table="magasins",
    model="pudo/magasin",
    projections=(Projection("fin_activite", ("FinActivite",), "string", "text"),),
    indexes=(),
    keys=("$.Code",),
    expiries=(FIN,),
)
ABSENTS = missing_rule(30, "magasins-import")
PEREMPTION = expiry_rule(FIN)


class _Db:
    """Doublure : elle rend les fenêtres qu'on lui donne, puis ce que la suppression sort."""

    def __init__(self, fenetres: list[list[dict[str, Any]]] | None = None) -> None:
        self.fenetres = fenetres or []
        self.instructions: list[str] = []
        self.supprimes: list[list[int]] = []
        # Le contenu des events écrits : leur type, et leurs propriétés en JSON.
        self.types: list[str] = []
        self.proprietes: list[str] = []

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.instructions.append(query)
        if query.lstrip().startswith("DELETE"):
            self.supprimes.append(list(args[0]))
            return [{"cle": f'["{ident}"]', "objet": '{"Code": "x"}'} for ident in args[0]]
        if "event_object_sequences" in query:
            # La réservation des numéros de séquence du journal : le lot d'events en
            # dépend, et une doublure qui ne la sert pas fait lever le socle.
            return [
                {"object_kind": kind, "object_id": ident, "last_sequence": 1}
                for kind, ident in zip(args[0], args[1], strict=True)
            ]
        return self.fenetres.pop(0) if self.fenetres else []

    async def execute(self, query: str, *args: Any) -> str:
        self.instructions.append(query)
        if "INSERT INTO events" in query:
            self.types += list(args[1])
            self.proprietes += list(args[6])
        return "INSERT 0 1"

    def is_in_transaction(self) -> bool:
        return True

    def transaction(self) -> Any:
        return _Rien()


class _Rien:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


def _processing(db: _Db) -> Processing:
    return Processing(
        db=db,  # type: ignore[arg-type]
        catalog=EventTypeCatalog(frozenset({OBJECT_REMOVED_EVENT})),
        now=lambda: MAINTENANT,
        budget=1000,
        author=EventAuthor("api_key", "k-1"),
        ingestion_id="ing-1",
        model_version=1,
    )


def _candidat(ident: int, valeur: str) -> dict[str, Any]:
    return {"id": ident, "cle": f'["M-{ident}"]', "valeur": valeur}


class TestLeSeuil:
    def test_le_seuil_d_une_peremption_est_une_date_ISO_et_non_un_instant(self) -> None:
        """La colonne projetée est `text` à dessein : le seuil doit l'être aussi."""
        assert threshold(PEREMPTION, MAINTENANT) == (MAINTENANT - timedelta(days=10)).isoformat()

    def test_le_seuil_des_absents_reste_un_INSTANT(self) -> None:
        """`absent_depuis` est une vraie `timestamptz` : la comparer à du texte aurait
        demandé une conversion, c'est-à-dire exactement ce qu'on s'interdit ailleurs."""
        assert threshold(ABSENTS, MAINTENANT) == MAINTENANT - timedelta(days=30)


class TestLesInstructions:
    def test_la_colonne_n_est_CONVERTIE_dans_aucune_clause(self) -> None:
        """Arbitrage de Gael : « on déplace le seuil ». Une conversion perd l'index
        déclaré ET fait échouer la requête entière sur une seule valeur inconvertible."""
        for sql in (
            scan_statement(TABLE, PEREMPTION),
            page_statement(TABLE, PEREMPTION),
            count_statement(TABLE, PEREMPTION),
        ):
            assert '"fin_activite"::' not in sql
            assert "::date" not in sql and "::timestamp" not in sql

    def test_la_selection_d_une_peremption_s_ordonne_sur_SA_colonne(self) -> None:
        """C'est ce qui emprunte l'index déclaré : plage sur la colonne, ordre sur la
        colonne. Trier sur `cle` aurait fait choisir l'index de la clé et parcourir."""
        assert 'ORDER BY c."fin_activite", c.cle' in scan_statement(TABLE, PEREMPTION)
        assert 'ORDER BY c."fin_activite", c.cle, c.id' in page_statement(TABLE, PEREMPTION)

    def test_une_peremption_exige_la_FORME_d_une_date_en_SQL(self) -> None:
        """Garde mesurée : une valeur non datée trie au-dessus du seuil — donc survit —
        SAUF si elle commence par un chiffre inférieur à 2, et celle-là serait supprimée
        à tort. Le motif l'écarte sans convertir quoi que ce soit."""
        assert ISO_DATE_RE in scan_statement(TABLE, PEREMPTION)
        assert ISO_DATE_RE not in scan_statement(TABLE, ABSENTS)

    def test_les_deux_regles_ne_comparent_pas_avec_LE_MEME_operateur(self) -> None:
        """« plus vieille que N jours » est strict ; « propriété + délai est passée » se
        lit antérieure OU ÉGALE à maintenant."""
        assert 'c."fin_activite" <= $1' in scan_statement(TABLE, PEREMPTION)
        assert 'c."absent_depuis" < $1' in scan_statement(TABLE, ABSENTS)

    def test_la_page_de_restitution_ne_SUPPRIME_rien(self) -> None:
        """Elle doit répondre à « montre-moi ce que tu supprimerais »."""
        sql = page_statement(TABLE, PEREMPTION)

        assert "DELETE" not in sql.upper()
        assert sql.lstrip().startswith("SELECT")

    def test_la_suppression_REND_l_objet_entier(self) -> None:
        """Sans lui, l'event ne porterait qu'une clé et la suppression ne se rattraperait
        pas : la ligne n'existe plus."""
        from environnement.ingestion.cleanup import delete_statement

        sql = delete_statement(TABLE)

        assert "RETURNING c.cle, c.objet" in sql
        assert "c.id = ANY($1::bigint[])" in sql


class TestLaValeurRelue:
    def test_une_forme_de_date_qui_n_EST_pas_une_date_n_est_pas_supprimable(self) -> None:
        """Le motif SQL dit la forme, jamais la validité : « 2026-02-30 » le satisfait."""
        assert removable(PEREMPTION, "2026-02-30") is False

    def test_une_vraie_date_l_est(self) -> None:
        assert removable(PEREMPTION, "2026-02-28") is True
        assert removable(PEREMPTION, "2026-02-28T10:00:00+00:00") is True

    def test_la_regle_des_absents_ne_relit_RIEN(self) -> None:
        """Sa colonne est une vraie date, posée par nous : il n'y a rien à valider."""
        assert removable(ABSENTS, None) is True


class TestLesReglesDUnStorage:
    def _source(self, nom: str, storage: str, *entrees: Entry) -> SourceDoc:
        return SourceDoc(nom, nom.title(), storage, entrees)

    def _entree(self, jours: int | None, *, fichier: bool = True) -> Entry:
        return Entry(
            kind="web",
            source_model="pudo/magasin-import",
            chain="vers-magasins",
            modes=EntryModes(element=False, batch=False, file=fichier),
            split="$.magasins[*]",
            unified_transaction=False,
            write_batch=2,
            missing_removed_after_days=jours,
        )

    def test_une_entree_qui_n_offre_PAS_le_mode_fichier_ne_porte_pas_la_regle(self) -> None:
        """Seul un dépôt de fichier prétend porter l'image complète ; l'autre cas est
        refusé à la saisie, et il ne doit pas non plus s'appliquer s'il traîne."""
        sources = [self._source("magasins-import", "magasins", self._entree(30, fichier=False))]

        assert [r.kind for r in rules_of(TABLE, sources)] == [KIND_EXPIRY]

    def test_une_source_qui_alimente_un_AUTRE_storage_n_y_change_rien(self) -> None:
        sources = [self._source("autre", "comptes", self._entree(5))]

        assert [r.kind for r in rules_of(TABLE, sources)] == [KIND_EXPIRY]

    def test_deux_entrees_de_la_meme_source_donnent_le_delai_le_PLUS_COURT(self) -> None:
        """C'est lui qui décide en pratique : le premier import qui l'atteint supprime."""
        sources = [self._source("magasins-import", "magasins", self._entree(30), self._entree(7))]

        absents = next(r for r in rules_of(TABLE, sources) if r.kind == KIND_MISSING)
        assert absents.days == 7
        assert absents.source == "magasins-import"

    def test_un_storage_sans_regle_n_en_rend_AUCUNE(self) -> None:
        """Le défaut : un paramétrage déjà écrit ne se met pas à supprimer."""
        nu = StorageTable(**{**vars(TABLE), "expiries": ()})

        assert rules_of(nu, [self._source("magasins-import", "magasins", self._entree(None))]) == []

    def test_le_nom_d_une_regle_vient_de_ce_qu_elle_EST_et_non_de_son_rang(self) -> None:
        """Un rang changerait de sens dès qu'une règle est ajoutée devant."""
        assert rule_id(PEREMPTION) == "peremption:$.FinActivite"
        assert rule_id(ABSENTS) == "absents:magasins-import"


class TestLeBalayage:
    @pytest.mark.asyncio
    async def test_une_regle_NON_RESOLUE_refuse_tout_le_nettoyage_du_storage(self) -> None:
        """Critère 10, et c'est un fail closed : y compris les AUTRES règles du même
        storage, dont on ne sait pas si elles étaient censées porter seules."""
        casse = StorageTable(**{**vars(TABLE), "unresolved_expiries": ("$.Disparue",)})
        db = _Db([[_candidat(1, "2026-01-01")]])

        assert (
            await db_remove_designated(_processing(db), casse, [PEREMPTION], now=MAINTENANT) is None
        )
        assert db.instructions == []

    @pytest.mark.asyncio
    async def test_aucune_regle_declaree_rend_ZERO_et_ne_touche_a_rien(self) -> None:
        """Zéro et `None` ne disent pas la même chose : l'un est un nettoyage qui n'avait
        rien à sortir, l'autre un nettoyage refusé."""
        db = _Db()

        assert await db_remove_designated(_processing(db), TABLE, [], now=MAINTENANT) == 0
        assert db.instructions == []

    @pytest.mark.asyncio
    async def test_le_balayage_enchaine_les_FENETRES_jusqu_a_les_epuiser(self) -> None:
        """Le lot n'est jamais tenu en mémoire : un export réel compte 168 775 items."""
        pleine = [_candidat(rang, "2026-01-01") for rang in range(REMOVAL_WINDOW)]
        db = _Db([pleine, [_candidat(999, "2026-01-02")]])

        supprimes = await db_remove_designated(_processing(db), TABLE, [PEREMPTION], now=MAINTENANT)

        assert supprimes == REMOVAL_WINDOW + 1
        assert db.supprimes == [[c["id"] for c in pleine], [999]]

    @pytest.mark.asyncio
    async def test_une_valeur_NON_DATEE_n_est_pas_supprimee_et_n_arrete_pas_le_balayage(
        self,
    ) -> None:
        """Critère 12. Le curseur avance PAR-DESSUS elle : une reprise depuis le début la
        relirait sans fin, et le balayage ne terminerait jamais."""
        db = _Db([[_candidat(1, "2026-02-30"), _candidat(2, "2026-01-01")]])

        supprimes = await db_remove_designated(_processing(db), TABLE, [PEREMPTION], now=MAINTENANT)

        assert supprimes == 1
        assert db.supprimes == [[2]]

    @pytest.mark.asyncio
    async def test_une_fenetre_ENTIEREMENT_non_datee_ne_supprime_ni_ne_tourne_en_rond(
        self,
    ) -> None:
        """Le cas où le `DELETE` n'a rien à faire : il ne doit pas partir à vide."""
        db = _Db([[_candidat(1, "2026-02-30")]])

        assert await db_remove_designated(_processing(db), TABLE, [PEREMPTION], now=MAINTENANT) == 0
        assert db.supprimes == []

    @pytest.mark.asyncio
    async def test_chaque_regle_balaie_a_son_tour_et_les_comptes_s_ADDITIONNENT(self) -> None:
        db = _Db([[_candidat(1, "2026-01-01")], [_candidat(2, "2026-01-01")]])

        supprimes = await db_remove_designated(
            _processing(db), TABLE, [ABSENTS, PEREMPTION], now=MAINTENANT
        )

        assert supprimes == 2
        assert db.supprimes == [[1], [2]]
        # Une fenêtre incomplète arrête la règle : elle dit qu'il n'y a plus rien après,
        # et un balayage de plus aurait coûté un aller-retour par règle sur chaque import.
        assert db.instructions.count("DELETE") == 0

    @pytest.mark.asyncio
    async def test_l_event_de_chaque_suppression_porte_l_OBJET_ENTIER_et_sa_regle(self) -> None:
        """Critère 7, et l'interdit que Gael a posé le premier : une suppression sans
        trace ne se rattrape pas. La clé seule ne permettrait pas de reposer la ligne."""
        db = _Db([[_candidat(1, "2026-01-01")]])

        await db_remove_designated(_processing(db), TABLE, [PEREMPTION], now=MAINTENANT)

        assert db.types == [OBJECT_REMOVED_EVENT]
        porte = json.loads(db.proprietes[0])
        assert porte["objet"] == {"Code": "x"}
        assert porte["rule"] == KIND_EXPIRY
        assert porte["property"] == "$.FinActivite"
        assert porte["days"] == 10
        assert porte["ingestion"] == "ing-1"
