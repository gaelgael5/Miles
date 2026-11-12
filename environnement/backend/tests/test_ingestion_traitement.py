"""L'orchestration du traitement d'un lot : l'ordre des contrôles, et ce qui est rejeté.

Sur une doublure de base — la base elle-même est éprouvée par la campagne d'intégration,
où l'écriture différentielle se mesure contre PostgreSQL. Ici on éprouve ce que la base ne
peut pas dire : qu'un objet fautif est rejeté SEUL, que la raison nommée est la bonne, et
que l'ordre des trois contrôles envoie corriger au bon endroit.

La doublure rejoue le CONTRAT de l'instruction de fusion — ses générations, ses lignes
rendues —, pas le `ON CONFLICT` de PostgreSQL. Un test qui prétendrait éprouver l'écriture
différentielle ici éprouverait la doublure : c'est la leçon du 29/10/2026, et la campagne
d'intégration s'en charge.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pytest
from miles_socle.events.model import EventAuthor

from environnement.event_types import code_event_catalog
from environnement.ingestion.outcome import (
    REJECT_KEY_MISSING,
    REJECT_MANUAL,
    REJECT_MODEL,
    REJECT_TRANSFORM,
    REJECTED,
    UNCHANGED,
    WRITTEN,
)
from environnement.ingestion.writeback import (
    NotServed,
    Prepared,
    Processing,
    file_prepare,
    resolve_process,
)

MODELE = """
$schema: https://json-schema.org/draft/2020-12/schema
$id: miles:/domains/pudo/site
title: Site
type: object
required: [Code, Libelle]
properties:
  Code: {type: string}
  Libelle: {type: string}
  # NULLABLE, et c'est ce qu'un modèle réel doit faire d'une propriété facultative :
  # mesuré le 03/11/2026, un template d'objet rend `null` pour un chemin ABSENT de la
  # source — la propriété est écrite avec une valeur nulle, elle n'est pas omise. Un
  # `{type: integer}` ferait donc rejeter pour non-conformité tout objet sans `postes`,
  # et l'auteur du template chercherait longtemps pourquoi.
  Postes: {type: [integer, "null"]}
"""
STORAGE = """
nom: "sites"
libelle: "Sites"
modele: "pudo/site"
cle:
  - "$.Code"
index: []
"""
# Une étape qui renomme : c'est ce qui rend l'empreinte insensible aux champs que le
# template ne lit pas, et donc le critère 4 éprouvable.
TEMPLATE = '{ "Code": $.code, "Libelle": $.nom, "Postes": $.postes#integer }'
CHAIN = """
{"format_version": 1, "slug": "vers-site", "label": "Vers site",
 "steps": [{"name": "convertir", "template": "convertir.jslt", "target": null}]}
"""


def _arbre(**fichiers: str) -> dict[str, str]:
    return {
        "domains/pudo/messages/site.yaml": MODELE,
        "storages/sites.yaml": STORAGE,
        "transformations/vers-site/chain.json": CHAIN,
        "transformations/vers-site/convertir.jslt": TEMPLATE,
        **fichiers,
    }


async def _prepare(fichiers: dict[str, str], storage: str = "sites") -> Prepared:
    async def read(path: str) -> str | None:
        return fichiers.get(path)

    return await file_prepare(read, list(fichiers), storage, "vers-site")


class _Db:
    """Doublure : elle enregistre les écritures et rend ce que la base rendrait.

    `deja` dit ce que la table porte DÉJÀ pour une clé : rien (création), « import » avec
    une empreinte (mise à jour), ou « manuel » (refus). C'est exactement ce que la CTE
    `avant` de l'instruction réelle lit.
    """

    def __init__(self, deja: dict[str, tuple[str, bytes | None]] | None = None) -> None:
        self.deja = deja or {}
        self.ecritures: list[str] = []
        self.events: list[str] = []
        self.sequences: dict[tuple[str, str], int] = {}

    def is_in_transaction(self) -> bool:
        return True

    async def execute(self, query: str, *args: Any) -> str:
        # Le journal écrit DEUX instructions par lot — les lignes d'events, puis leurs
        # objets. On ne retient que la première, et son tableau de types : compter les
        # exécutions ferait compter un event par instruction là où il y en a N.
        if "INTO events" in query:
            self.events.extend(args[1])
        return "OK"

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        if "event_object_sequences" in query:
            return self._numeros(args)
        if query.lstrip().startswith("WITH candidats"):
            return self._fusion(args)
        raise AssertionError(f"requête inattendue : {query[:40]}")

    def _numeros(self, args: tuple[Any, ...]) -> list[Any]:
        """Les numéros de séquence que le journal réserve pour les objets d'un lot.

        Doublée fidèlement au CONTRAT de la requête — UNE ligne par objet distinct, portant
        le DERNIER numéro attribué — et non à ce qu'on croit qu'elle rend : une ligne par
        occurrence ferait croire au journal que ses numéros sont contigus alors qu'ils se
        chevaucheraient.
        """
        rendus: list[Any] = []
        for couple, combien in Counter(zip(args[0], args[1], strict=True)).items():
            dernier = self.sequences.get(couple, 0) + combien
            self.sequences[couple] = dernier
            rendus.append(
                {"object_kind": couple[0], "object_id": couple[1], "last_sequence": dernier}
            )
        return rendus

    def _fusion(self, args: tuple[Any, ...]) -> list[Any]:
        """La fusion d'UNE génération, telle que l'instruction réelle la rend.

        Les générations sont le cœur du contrat : les premières occurrences d'une clé
        partent en 1, les deuxièmes en 2, et c'est ce qui préserve « le dernier valide
        gagne ». La doublure les recalcule au lieu de les supposer — sinon un lot portant
        deux fois la même clé passerait ici et échouerait sur la base.
        """
        generation, positions, cles, empreintes = args[2], args[3], args[4], args[6]
        candidats = list(zip(positions, cles, empreintes, strict=True))
        rangs: Counter[str] = Counter()
        numerotes = []
        for position, cle, empreinte in sorted(candidats):
            rangs[cle] += 1
            numerotes.append((position, cle, empreinte, rangs[cle]))
        generations = max(Counter(cle for _, cle, _ in candidats).values())
        rendus: list[Any] = []
        for position, cle, empreinte, rang in numerotes:
            if rang != generation:
                continue
            origine, empreinte_avant = self.deja.get(cle, (None, None))
            if origine != "manuel":
                self.deja[cle] = ("import", empreinte)
                self.ecritures.append(cle)
            rendus.append(
                {
                    "position": position,
                    "cle": cle,
                    "posee": origine != "manuel",
                    "origine_avant": origine,
                    "identique": empreinte_avant is not None and empreinte_avant == empreinte,
                    "generations": generations,
                }
            )
        return rendus

    def transaction(self) -> Any:
        return _Rien()


class _Rien:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_: object) -> None:
        return None


def _processing(db: _Db) -> Processing:
    return Processing(
        db=db,
        catalog=code_event_catalog(),
        now=lambda: datetime(2026, 11, 3, 12, tzinfo=UTC),
        budget=100_000,
        author=EventAuthor("apikey", "k-1"),
        ingestion_id="a" * 32,
        model_version=7,
    )


SAIN = {"code": "S-1", "nom": "Site un", "postes": 3}


class TestPreparation:
    @pytest.mark.asyncio
    async def test_le_storage_le_modele_et_la_chaine_sont_lus_ET_COMPILES_une_fois(
        self,
    ) -> None:
        prepare = await _prepare(_arbre())

        assert prepare.table.storage == "sites"
        assert prepare.table.keys == ("$.Code",)
        # Le modèle est lu, et son validateur CONSTRUIT une fois pour le dépôt ; la règle
        # de clé est compilée de même — 372,5 µs par jpath, qui étaient payés à chaque
        # objet avant le 06/11/2026.
        assert prepare.validator.schema["title"] == "Site"
        assert prepare.keys.chemins == (("Code",),)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("retire", "attendu"),
        [
            ("storages/sites.yaml", "storage:sites"),
            # Le modèle absent fait refuser le STORAGE, parce que c'est lui qui donne le
            # type des colonnes : le refus nomme donc le storage ET le motif. Vérifié
            # plutôt que supposé — le motif est ce qui envoie corriger au bon endroit.
            ("domains/pudo/messages/site.yaml", "storage:sites:modele_absent"),
            ("transformations/vers-site/chain.json", "chaine:"),
            ("transformations/vers-site/convertir.jslt", "chaine:"),
        ],
        ids=["storage", "modele", "enchainement", "template"],
    )
    async def test_ce_que_la_version_servie_ne_porte_pas_est_NOMME(
        self, retire: str, attendu: str
    ) -> None:
        # Un refus de DÉPÔT, pas deux cents rejets d'objets : aucun objet du lot ne
        # pourrait aboutir, et le `detail` dit lequel des trois manque.
        fichiers = _arbre()
        del fichiers[retire]

        with pytest.raises(NotServed) as refus:
            await _prepare(fichiers)

        assert refus.value.detail.startswith(attendu)


class TestTraitement:
    @pytest.mark.asyncio
    async def test_un_objet_sain_est_ecrit_et_porte_sa_cle(self) -> None:
        db = _Db()

        rapport = await resolve_process(_processing(db), await _prepare(_arbre()), [SAIN])

        assert [(o.outcome, o.key) for o in rapport.objects] == [(WRITTEN, '["S-1"]')]
        assert (rapport.written, rapport.unchanged, rapport.rejected) == (1, 0, 0)
        # Un event par objet ÉCRIT (Gael, 03/11/2026).
        assert len(db.events) == 1

    @pytest.mark.asyncio
    async def test_un_objet_inchange_n_ecrit_rien_et_ne_produit_AUCUN_event(self) -> None:
        prepare = await _prepare(_arbre())
        db = _Db()
        await resolve_process(_processing(db), prepare, [SAIN])
        db.events.clear()

        rapport = await resolve_process(_processing(db), prepare, [SAIN])

        assert [o.outcome for o in rapport.objects] == [UNCHANGED]
        # Pas de modification, donc pas d'event : c'est le DELTA qui parle, jamais le
        # fait que le code ait tourné (leçon du 02/11/2026).
        assert db.events == []

    @pytest.mark.asyncio
    async def test_un_objet_fautif_est_rejete_SEUL(self) -> None:
        db = _Db()
        lot: list[dict[str, object]] = [SAIN, {"code": "S-2"}, {"code": "S-3", "nom": "Trois"}]

        rapport = await resolve_process(_processing(db), await _prepare(_arbre()), lot)

        assert [o.outcome for o in rapport.objects] == [WRITTEN, REJECTED, WRITTEN]
        assert rapport.objects[1].reason == REJECT_MODEL
        assert db.ecritures == ['["S-1"]', '["S-3"]']
        # LA CLÉ EST NOMMÉE bien que l'objet soit refusé (story `82bc9dca`) : c'est elle
        # qui dit à l'appelant lequel de ses items corriger, et c'est elle qui empêche le
        # marquage des absents de supprimer, au bout du délai, un item dont le document
        # parlait fidèlement.
        assert rapport.objects[1].key == '["S-2"]'

    @pytest.mark.asyncio
    async def test_une_transformation_en_echec_nomme_l_etape_et_la_cause(self) -> None:
        db = _Db()
        # `#integer` sur une valeur qui n'en est pas une : le moteur refuse, et c'est
        # l'objet qui est rejeté, pas le lot.
        rapport = await resolve_process(
            _processing(db),
            await _prepare(_arbre()),
            [{"code": "S-1", "nom": "A", "postes": "beaucoup"}],
        )

        issue = rapport.objects[0]
        assert (issue.outcome, issue.reason) == (REJECTED, REJECT_TRANSFORM)
        assert issue.detail is not None and "etape 0" in issue.detail
        # La clé reste NULLE ici, et le rang est la seule prise de l'appelant : la
        # transformation a échoué, donc il n'existe aucun objet d'où l'extraire. C'est la
        # frontière de la décision du 09/11/2026, qui nomme la clé d'un rejet de MODÈLE.
        assert issue.key is None

    @pytest.mark.asyncio
    async def test_une_cle_absente_du_RESULTAT_est_rejetee_avec_son_rang(self) -> None:
        """Le cas se présente quand le MODÈLE autorise le nul sur la propriété de clé.

        Mesuré le 03/11/2026 : le moteur rend `null` pour un chemin absent dans un
        template d'objet — la propriété est bien là, avec une valeur nulle. Un modèle qui
        type la clé en `string` rejette donc l'objet pour NON-CONFORMITÉ avant d'en venir
        à la clé, et c'est le meilleur des deux messages. « Clé non extractible » ne
        survient que sur un modèle qui admet le nul là où il met son identité, et c'est
        alors le jpath qu'il faut nommer, pas le modèle.
        """
        nullable = MODELE.replace("Code: {type: string}", 'Code: {type: [string, "null"]}')
        fichiers = _arbre(
            **{
                "domains/pudo/messages/site.yaml": nullable.replace(
                    "required: [Code, ", "required: ["
                )
            }
        )
        db = _Db()

        rapport = await resolve_process(
            _processing(db), await _prepare(fichiers), [{"nom": "Sans code"}]
        )

        issue = rapport.objects[0]
        assert (issue.position, issue.outcome, issue.reason) == (0, REJECTED, REJECT_KEY_MISSING)
        assert issue.detail == "$.Code"
        assert issue.key is None
        assert db.ecritures == []

    @pytest.mark.asyncio
    async def test_un_modele_qui_TYPE_sa_cle_rejette_pour_non_conformite_d_abord(self) -> None:
        # L'ordre des trois contrôles, éprouvé : transformation, modèle, clé. Le même
        # objet rejeté pour la clé ci-dessus l'est pour le modèle ici, et c'est voulu —
        # « $['Code'] : None n'est pas une chaîne » envoie corriger le template.
        db = _Db()

        rapport = await resolve_process(
            _processing(db), await _prepare(_arbre()), [{"nom": "Sans code"}]
        )

        issue = rapport.objects[0]
        assert (issue.outcome, issue.reason) == (REJECTED, REJECT_MODEL)
        assert issue.detail is not None and issue.detail.startswith("$['Code']")

    @pytest.mark.asyncio
    async def test_un_objet_d_origine_MANUELLE_n_est_jamais_ecrase_par_un_import(self) -> None:
        db = _Db({'["S-1"]': ("manuel", b"\x01")})

        rapport = await resolve_process(_processing(db), await _prepare(_arbre()), [SAIN])

        issue = rapport.objects[0]
        assert (issue.outcome, issue.reason, issue.key) == (REJECTED, REJECT_MANUAL, '["S-1"]')
        assert db.ecritures == []
        assert db.events == []

    @pytest.mark.asyncio
    async def test_deux_objets_de_meme_cle_le_dernier_gagne_et_l_anomalie_est_DITE(self) -> None:
        db = _Db()
        lot: list[dict[str, object]] = [
            {"code": "S-1", "nom": "Premier"},
            {"code": "S-1", "nom": "Dernier"},
        ]

        rapport = await resolve_process(_processing(db), await _prepare(_arbre()), lot)

        # Décision de Gael du 02/11/2026 : le dernier gagne. Et le compte-rendu le
        # SIGNALE — écrire le dernier en silence laisserait une source se contredire
        # sans que personne ne l'apprenne (critère 8).
        assert [o.outcome for o in rapport.objects] == [WRITTEN, WRITTEN]
        assert db.ecritures == ['["S-1"]', '["S-1"]']
        assert rapport.anomalies == ['cle_en_double_dans_le_lot:["S-1"]']

    @pytest.mark.asyncio
    async def test_un_lot_entierement_rejete_le_dit_et_n_ecrit_rien(self) -> None:
        db = _Db()

        rapport = await resolve_process(
            _processing(db), await _prepare(_arbre()), [{"code": "a"}, {"code": "b"}]
        )

        assert rapport.all_rejected is True
        assert db.ecritures == []

    @pytest.mark.asyncio
    async def test_un_lot_VIDE_est_traite_sans_rien_ecrire_et_sans_echouer(self) -> None:
        db = _Db()

        rapport = await resolve_process(_processing(db), await _prepare(_arbre()), [])

        assert (rapport.received, rapport.all_rejected) == (0, False)
        assert db.ecritures == []

    @pytest.mark.asyncio
    async def test_une_chaine_SANS_etape_rend_l_objet_source_tel_quel(self) -> None:
        # Licite, et voulu : une source dont le modèle d'entrée est déjà celui du storage
        # n'a pas à écrire un template identité pour ne rien faire.
        vide = '{"format_version": 1, "slug": "vers-site", "label": "V", "steps": []}'
        fichiers = _arbre(**{"transformations/vers-site/chain.json": vide})
        db = _Db()

        rapport = await resolve_process(
            _processing(db), await _prepare(fichiers), [{"Code": "S-9", "Libelle": "Neuf"}]
        )

        assert [(o.outcome, o.key) for o in rapport.objects] == [(WRITTEN, '["S-9"]')]
