"""L'écriture ENSEMBLIÈRE des objets préparés : un upsert par paquet, et son compte-rendu.

**Une instruction pour tout un paquet, et non une par objet** (Gael, 06/11/2026 : « pour
des raisons d'optimisation il faut que ce soit rapide et optimisé »). L'ancienne écriture
faisait un aller-retour par objet, soit cinquante mille `fetchrow` pour un document de
cinquante mille items — dans la transaction que le critère 9 veut COURTE.

**Pourquoi `INSERT … ON CONFLICT … RETURNING` et non le mot-clé `MERGE`.** Les stacks sont
en PostgreSQL 16, où `MERGE` ne sait pas faire `RETURNING` (arrivé en 17). Or le sort de
CHAQUE ligne — créée, modifiée, inchangée, refusée parce que d'origine manuelle — est
exigé deux fois : par le compte-rendu, et par la règle « un event par objet écrit ». Avec
`MERGE`, il faudrait réinterroger la table après coup : des allers-retours de plus, et une
lecture qui n'est plus celle de l'instantané de l'écriture. C'est le même upsert, dans la
seule forme que PG 16 sait raconter — à réécrire en `MERGE … RETURNING merge_action()` le
jour où les stacks passeront en 17, pas avant.

**Les items de même clé sont écrits par GÉNÉRATIONS**, et c'est ce qui préserve « deux
objets de même clé dans un même lot : le dernier valide gagne » (décision du 02/11/2026).
Deux lignes de même clé dans un seul `ON CONFLICT DO UPDATE` font échouer l'instruction
entière (« cannot affect row a second time ») : on ne peut donc pas tout écrire d'un coup.
Dédoublonner en ne gardant que la dernière aurait été plus simple — et aurait changé le
compte-rendu, qui nomme aujourd'hui le sort de CHAQUE position. Les premières occurrences
partent donc en génération 1, les deuxièmes en génération 2, et ainsi de suite : un
document sain n'a qu'une génération, donc une instruction par paquet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from environnement.ingestion.preparation import PreparedObject
from environnement.ingestion.staging import PREPARED_TABLE, STAGED_TO_WRITE
from environnement.storages.ddl import quoted
from environnement.storages.model import ABSENCE_COLUMN, StorageTable

# L'origine d'une ligne de storage. Un objet posé à la main n'est jamais écrasé par un
# import : c'est la seule chose qui distingue les deux, et elle décide d'un refus.
MANUAL_ORIGIN = "manuel"
IMPORT_ORIGIN = "import"


# Combien d'items une SEULE instruction de fusion traite. Borné ici, et non laissé au
# `lot_ecriture` de la source, parce que le coût par item CROÎT avec la taille de la
# fenêtre. Mesuré le 06/11/2026 sur `host-test-37`, cinquante mille objets réimportés :
#
#   fenêtre   100 →  4,75 s     fenêtre  1000 → 12,51 s
#   fenêtre   500 →  7,91 s     fenêtre  5000 → 54,68 s
#
# La cause est la même qu'à la jointure de `avant` : les CTE n'ont pas de statistiques,
# donc `generation = $3` est estimé à 1/200 quelle que soit la fenêtre réelle, et les
# jointures finales sont planifiées pour deux cent cinquante lignes. Plus la fenêtre
# s'éloigne de cette estimation, plus le plan est faux — jusqu'à ne plus rendre du tout.
#
# `lot_ecriture` garde donc son sens — TOUS LES COMBIEN on valide — et ne décide plus de la
# taille d'une instruction : l'administrateur peut l'augmenter sans tomber dans la falaise.
MERGE_WINDOW = 100


class MergeDb(Protocol):
    async def fetch(self, query: str, *args: Any) -> list[Any]: ...


@dataclass(frozen=True)
class WriteResult:
    """Ce que la base a fait d'un objet. `refused` : la ligne existante est manuelle."""

    created: bool
    changed: bool
    refused: bool

    @property
    def written(self) -> bool:
        return self.created or self.changed


@dataclass(frozen=True)
class MergedObject:
    """Ce que la base a fait de l'objet de ce rang. `key` est forcément là : un item sans
    clé n'est pas écrivable, et n'entre donc jamais dans un paquet à fusionner."""

    position: int
    key: str
    result: WriteResult


# La fenêtre d'items à écrire, lue DANS la table temporaire de l'import : les objets ne
# remontent jamais jusqu'à Python entre la préparation et la table finale. C'est tout
# l'objet du dispositif — la copie en masse les a posés en base, la fusion les y déplace.
# S608 : les deux seules valeurs interpolées sont des constantes de ce dépôt — le nom de
# la table temporaire et le libellé d'un sort. Les bornes de la fenêtre sont des paramètres.
_SOURCE_PREPARED = f"""
    SELECT position, cle, objet, empreinte
    FROM pg_temp.{PREPARED_TABLE}
    WHERE outcome = '{STAGED_TO_WRITE}' AND position > $4 AND position <= $5
"""  # noqa: S608

# Les items qu'un appel porte dans sa charge utile (modes `element` et `tableau`, deux
# cents objets au plus) : ils sont déjà en mémoire, et les copier dans une table
# temporaire pour les relire aussitôt aurait ajouté un DDL par requête HTTP.
_SOURCE_INLINE = """
    SELECT position, cle, objet::jsonb AS objet, empreinte
    FROM unnest($4::integer[], $5::text[], $6::text[], $7::bytea[])
         AS t(position, cle, objet, empreinte)
"""


def _statement(table: StorageTable, source: str) -> str:
    """L'instruction de fusion d'un paquet. Les identités sont CITÉES, jamais concaténées.

    `quoted` refuse ce qui n'est pas un nom : le schéma et la table viennent d'un
    paramétrage venu du réseau, et PostgreSQL n'a pas de requête paramétrée pour une
    identité. C'est la même barrière que celle du DDL, au même endroit.

    Trois promesses tiennent dans cette seule instruction, et c'est voulu :

    - **`vu_le` avance TOUJOURS**, y compris sur un objet inchangé. C'est la date que le
      balayage lit ; ne pas l'avancer rendrait un objet réimporté à chaque fois
      indiscernable d'un objet oublié, et le balayage finirait par le sortir.
    - **`modifie_le` et le corps ne bougent QUE si l'empreinte change.** C'est la date de
      l'historique ; l'avancer à chaque import la rend inutile.
    - **un objet d'origine `manuel` n'est jamais écrasé par un import** : la clause du
      `DO UPDATE` l'écarte, et il n'est alors PAS rendu par `RETURNING` — c'est ainsi
      qu'on sait qu'il a été refusé, sans le relire.

    **Ce qui s'est passé est MESURÉ, pas déduit du fait que le code a tourné** : `avant`
    lit l'état d'avant l'écriture, sur le même instantané, et `ecrites` dit quelles lignes
    l'instruction a réellement posées. C'est la leçon du 02/11/2026 — une opération
    idempotente ne sait pas, par son texte, si elle a agi.
    """
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    # S608 signale l'assemblage, à juste titre : PostgreSQL n'a pas de requête paramétrée
    # pour une identité. Ce qui tient, et qui est tout ce qui tient : les SEULES valeurs
    # interpolées sont `cible`, passée par `quoted` — qui REFUSE ce qui n'est pas un nom
    # —, le fragment de source (un littéral de ce fichier) et deux littéraux d'origine.
    # Les clés, les objets, les empreintes, l'instant et la version partent en paramètres.
    return f"""
WITH candidats AS ({source}
), numerotes AS (
    SELECT position, cle, objet, empreinte,
           row_number() OVER (PARTITION BY cle ORDER BY position) AS generation,
           count(*) OVER (PARTITION BY cle) AS occurrences
    FROM candidats
), source AS (
    SELECT position, cle, objet, empreinte FROM numerotes WHERE generation = $3
), avant AS (
    -- **`source` MÈNE la jointure, et ce n'est pas cosmétique.** Écrit dans l'autre sens
    -- — `FROM {cible} c JOIN source s` —, PostgreSQL 16 plaçait la table CIBLE du côté
    -- extérieur et la parcourait en entier (`Seq Scan on cible`), en rescannant la CTE
    -- pour chaque ligne : l'index unique sur `cle` n'était pas utilisé du tout. La cause
    -- est que la CTE n'a pas de statistiques, donc son `generation = $3` est estimé à
    -- 1/200 — 250 lignes au lieu de la fenêtre entière — et un parcours complet paraît
    -- moins cher qu'il ne l'est. Mesuré le 06/11/2026 sur `host-test-37` : la fusion d'un
    -- seul coup de cinquante mille items ne rendait toujours pas au bout de 24 minutes.
    -- Avec `source` en tête, le plan est une boucle d'index — une recherche par item.
    SELECT s.cle, c.empreinte, c.origine FROM source s LEFT JOIN {cible} c ON c.cle = s.cle
), ecrites AS (
    INSERT INTO {cible} (cle, objet, empreinte, origine, vu_le, modifie_le, version_modele)
    SELECT s.cle, s.objet, s.empreinte, '{IMPORT_ORIGIN}', $1, $1, $2 FROM source s
    ON CONFLICT (cle) DO UPDATE SET
        vu_le = excluded.vu_le,
        -- GARDER L'ANCIEN DATUM, et non réécrire le même. Aucun test fonctionnel ne
        -- distingue les deux — la campagne d'injection du 03/11/2026 est restée verte en
        -- remplaçant ces trois lignes par « objet = excluded.objet ». Ce qui les tient est
        -- le TOAST : rendre le datum d'avant laisse PostgreSQL réutiliser son stockage
        -- hors ligne, alors qu'une valeur neuve le réécrit entièrement. Mesuré le même
        -- jour sur 200 objets de 12 ko réimportés 40 fois à l'identique : 2,6 Mo de TOAST
        -- avec ce CASE, 104 Mo sans — le facteur est le nombre de réimports.
        objet = CASE
            WHEN {cible}.empreinte = excluded.empreinte THEN {cible}.objet
            ELSE excluded.objet END,
        empreinte = excluded.empreinte,
        modifie_le = CASE
            WHEN {cible}.empreinte = excluded.empreinte THEN {cible}.modifie_le
            ELSE excluded.modifie_le END,
        version_modele = excluded.version_modele,
        -- LA MARQUE D'ABSENCE TOMBE dès qu'un dépôt reparle de l'item, quel que soit son
        -- mode et quel que soit son état final (Gael, 09/11/2026). C'est ce qui fait du
        -- délai une protection contre un export tronqué : un fichier amputé marque des
        -- items à tort, le fichier complet du lendemain les démarque, et rien n'a été
        -- supprimé entre-temps. Ici et non à la fin de l'import, parce que c'est la seule
        -- ligne qui sait QUELLES clés ont été portées — un import interrompu lève donc
        -- les marques des items qu'il a écrits, et pas des autres.
        {ABSENCE_COLUMN} = NULL
    WHERE {cible}.origine = '{IMPORT_ORIGIN}'
    RETURNING cle
)
SELECT s.position, s.cle,
       (e.cle IS NOT NULL) AS posee,
       a.origine AS origine_avant,
       (a.empreinte IS NOT NULL AND a.empreinte = s.empreinte) AS identique,
       (SELECT max(occurrences) FROM numerotes) AS generations
FROM source s
LEFT JOIN avant a ON a.cle = s.cle
LEFT JOIN ecrites e ON e.cle = s.cle
ORDER BY s.position
"""  # noqa: S608


async def db_merge_window(
    db: MergeDb,
    table: StorageTable,
    *,
    after: int,
    through: int,
    now: datetime,
    model_version: int,
) -> list[MergedObject]:
    """Fusionne les items à écrire dont le rang est dans `]after, through]`.

    Bornée par des RANGS et non par un `LIMIT` : la fenêtre doit être exactement celle que
    l'appelant a lue en métadonnées, et un `LIMIT` sur les seules lignes écrivables aurait
    désigné une autre tranche du document dès qu'un item y est rejeté.

    Rendu TRIÉ PAR RANG et non dans l'ordre des générations : c'est le rang du document
    que le compte-rendu nomme, et son plafond de détail garde les premiers rejets — les
    lire dans un autre ordre aurait fait garder d'autres rejets.
    """
    arguments = (after, through)
    return await _resolve_rounds(
        db, _statement(table, _SOURCE_PREPARED), arguments, now, model_version
    )


async def db_merge_items(
    db: MergeDb,
    table: StorageTable,
    items: list[PreparedObject],
    *,
    now: datetime,
    model_version: int,
) -> list[MergedObject]:
    """Fusionne les items à écrire d'un lot reçu dans l'appel, et rend leur sort."""
    ecrivables = [item for item in items if item.writable]
    statement = _statement(table, _SOURCE_INLINE)
    fusionnes: list[MergedObject] = []
    # Découpé en instructions de `MERGE_WINDOW` items : un lot reçu ne dépasse pas deux
    # cents objets aujourd'hui, mais le découpage tient la promesse du plan quel que soit
    # le plafond de demain, et deux items de même clé séparés par une tranche sont écrits
    # dans l'ordre des tranches — « le dernier valide gagne » tient sans les générations.
    for depart in range(0, len(ecrivables), MERGE_WINDOW):
        tranche = ecrivables[depart : depart + MERGE_WINDOW]
        arguments = (
            [item.position for item in tranche],
            [item.key for item in tranche],
            [json.dumps(item.objet, ensure_ascii=False) for item in tranche],
            [item.empreinte for item in tranche],
        )
        fusionnes += await _resolve_rounds(db, statement, arguments, now, model_version)
    return fusionnes


async def _resolve_rounds(
    db: MergeDb,
    statement: str,
    arguments: tuple[Any, ...],
    now: datetime,
    model_version: int,
) -> list[MergedObject]:
    """Une passe par génération, jusqu'à les avoir toutes. Une seule, sur un lot sain.

    Le nombre de générations est rendu PAR la première passe, et non demandé avant : une
    requête de comptage de plus aurait coûté un aller-retour à chaque paquet, pour une
    réponse qui vaut « une » dans la quasi-totalité des cas.
    """
    fusionnes: list[MergedObject] = []
    generation = 1
    generations = 1
    while generation <= generations:
        rows = await db.fetch(statement, now, model_version, generation, *arguments)
        if not rows:
            break
        generations = int(rows[0]["generations"])
        fusionnes.extend(_merged(row) for row in rows)
        generation += 1
    fusionnes.sort(key=lambda merged: merged.position)
    return fusionnes


def _merged(row: Any) -> MergedObject:
    origine_avant, posee = row["origine_avant"], bool(row["posee"])
    if not posee:
        if origine_avant != MANUAL_ORIGIN:
            # Jamais de repli : une ligne non posée dont l'origine n'est pas manuelle
            # voudrait dire que la clause du `DO UPDATE` a écarté autre chose que ce
            # qu'elle nomme, et le compte-rendu dirait « refusé » sans savoir pourquoi.
            raise ValueError(f"ligne non posée d'origine {origine_avant!r} : clause inattendue")
        return MergedObject(
            int(row["position"]),
            row["cle"],
            WriteResult(created=False, changed=False, refused=True),
        )
    resultat = WriteResult(
        created=origine_avant is None,
        changed=origine_avant is None or not bool(row["identique"]),
        refused=False,
    )
    return MergedObject(int(row["position"]), row["cle"], resultat)
