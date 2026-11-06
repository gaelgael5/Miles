"""La LECTURE de ce que la fusion rend : classer chaque ligne, et boucler les générations.

Ce qui est éprouvé ici est NOTRE part : traduire les trois colonnes rendues par
l'instruction — posée, origine d'avant, empreinte identique — en « créé », « modifié »,
« inchangé » ou « refusé », et redemander une passe tant qu'il reste des générations. La
sémantique du `ON CONFLICT` lui-même est celle de PostgreSQL, et c'est la campagne
d'intégration qui la mesure : une doublure qui la rejouerait ne prouverait que la doublure.

Les lignes rendues sont donc des lignes EN DUR, choisies pour être discriminantes — une
empreinte identique ET une création, par exemple, n'existe pas et ne doit pas être inventée.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from environnement.ingestion.preparation import PreparedObject
from environnement.ingestion.store_merge import WriteResult, db_merge_items
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


def _ligne(position: int, cle: str, **colonnes: Any) -> dict[str, Any]:
    forme = {
        "position": position,
        "cle": cle,
        "posee": True,
        "origine_avant": "import",
        "identique": False,
        "generations": 1,
    }
    forme.update(colonnes)
    return forme


def _item(position: int, cle: str | None = "S-1", reason: str | None = None) -> PreparedObject:
    if reason is not None:
        return PreparedObject(position, None, None, None, reason, "détail")
    return PreparedObject(position, cle, {"Code": cle}, b"\x01" * 32)


class _Db:
    """Doublure : elle rend les lignes qu'on lui donne, une passe par génération."""

    def __init__(self, passes: list[list[dict[str, Any]]]) -> None:
        self.passes = passes
        self.appels: list[tuple[Any, ...]] = []

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.appels.append(args)
        rang = len(self.appels) - 1
        return self.passes[rang] if rang < len(self.passes) else []


async def test_une_cle_absente_de_la_table_est_CREEE() -> None:
    db = _Db([[_ligne(0, "S-1", origine_avant=None)]])

    fusionnes = await db_merge_items(db, TABLE, [_item(0)], now=NOW, model_version=7)

    assert (fusionnes[0].result.created, fusionnes[0].result.written) == (True, True)


async def test_une_empreinte_IDENTIQUE_laisse_l_objet_inchange() -> None:
    """`vu_le` a bougé, le corps non : c'est « inchangé », et c'est le DELTA qui le dit."""
    db = _Db([[_ligne(0, "S-1", identique=True)]])

    fusionnes = await db_merge_items(db, TABLE, [_item(0)], now=NOW, model_version=7)

    assert fusionnes[0].result == WriteResult(created=False, changed=False, refused=False)


async def test_une_empreinte_DIFFERENTE_compte_une_modification() -> None:
    db = _Db([[_ligne(0, "S-1", identique=False)]])

    fusionnes = await db_merge_items(db, TABLE, [_item(0)], now=NOW, model_version=7)

    assert (fusionnes[0].result.created, fusionnes[0].result.written) == (False, True)


async def test_une_ligne_NON_POSEE_d_origine_manuelle_est_refusee() -> None:
    """La clause du `DO UPDATE` l'a écartée, et c'est son ABSENCE qui le dit — on ne
    relit pas la table pour l'apprendre."""
    db = _Db([[_ligne(0, "S-1", posee=False, origine_avant="manuel")]])

    fusionnes = await db_merge_items(db, TABLE, [_item(0)], now=NOW, model_version=7)

    assert fusionnes[0].result.refused and not fusionnes[0].result.written


async def test_une_ligne_non_posee_d_une_AUTRE_origine_leve() -> None:
    """Jamais de repli : « refusé » sans savoir pourquoi est un compte-rendu qui ment."""
    db = _Db([[_ligne(0, "S-1", posee=False, origine_avant="import")]])

    with pytest.raises(ValueError, match="clause inattendue"):
        await db_merge_items(db, TABLE, [_item(0)], now=NOW, model_version=7)


async def test_deux_items_de_meme_cle_demandent_DEUX_generations() -> None:
    """Le nombre de générations est rendu PAR la première passe, et la boucle le suit.

    C'est ce qui préserve « le dernier valide gagne » : deux lignes de même clé dans un
    seul `ON CONFLICT DO UPDATE` feraient échouer l'instruction entière.
    """
    db = _Db(
        [
            [_ligne(0, "S-1", origine_avant=None, generations=2)],
            [_ligne(1, "S-1", identique=False, generations=2)],
        ]
    )

    fusionnes = await db_merge_items(
        db, TABLE, [_item(0, "S-1"), _item(1, "S-1")], now=NOW, model_version=7
    )

    assert [m.position for m in fusionnes] == [0, 1]
    assert [args[2] for args in db.appels] == [1, 2]


async def test_une_seule_generation_ne_demande_qu_une_passe() -> None:
    """Le cas de tous les documents sains : une instruction par paquet, pas deux."""
    db = _Db([[_ligne(0, "S-1", origine_avant=None), _ligne(1, "S-2", origine_avant=None)]])

    await db_merge_items(db, TABLE, [_item(0, "S-1"), _item(1, "S-2")], now=NOW, model_version=7)

    assert len(db.appels) == 1


async def test_le_sort_est_rendu_TRIE_PAR_RANG_et_non_par_generation() -> None:
    """Le compte-rendu nomme des rangs du document, et son plafond garde les premiers."""
    db = _Db(
        [
            [
                _ligne(0, "S-1", origine_avant=None, generations=2),
                _ligne(5, "S-2", origine_avant=None, generations=2),
            ],
            [_ligne(2, "S-1", generations=2)],
        ]
    )
    items = [_item(0, "S-1"), _item(2, "S-1"), _item(5, "S-2")]

    fusionnes = await db_merge_items(db, TABLE, items, now=NOW, model_version=7)

    assert [m.position for m in fusionnes] == [0, 2, 5]


async def test_un_lot_SANS_item_ecrivable_ne_touche_pas_la_base() -> None:
    """Deux cents rejets de conformité ne doivent pas ouvrir une instruction pour rien."""
    db = _Db([])

    fusionnes = await db_merge_items(
        db, TABLE, [_item(0, reason="modele_non_respecte")], now=NOW, model_version=7
    )

    assert fusionnes == [] and db.appels == []


async def test_les_items_REJETES_ne_partent_pas_dans_la_charge_de_la_fusion() -> None:
    """Un rejet n'a ni objet ni empreinte : l'envoyer ferait écrire une ligne nulle."""
    db = _Db([[_ligne(1, "S-1", origine_avant=None)]])

    await db_merge_items(
        db,
        TABLE,
        [_item(0, reason="cle_non_extractible"), _item(1, "S-1")],
        now=NOW,
        model_version=7,
    )

    assert db.appels[0][3] == [1]
