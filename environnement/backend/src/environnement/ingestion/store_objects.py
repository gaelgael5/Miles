"""L'écriture DIFFÉRENTIELLE d'un objet dans la table de son storage.

Trois promesses tiennent dans une seule instruction, et c'est voulu :

- **`vu_le` avance TOUJOURS**, y compris sur un objet inchangé. C'est la date que le
  balayage lit ; ne pas l'avancer rendrait un objet réimporté à chaque fois indiscernable
  d'un objet oublié, et le balayage finirait par le sortir. (Correction du 26/10/2026 au
  ticket, qui interdisait l'inverse.)
- **`modifie_le` et le corps ne bougent QUE si l'empreinte change.** C'est la date de
  l'historique ; l'avancer à chaque import la rend inutile.
- **un objet d'origine `manuel` n'est jamais écrasé par un import** : aucun import ne le
  réécrira jamais, donc son `vu_le` ne bougera plus, et c'est ce qui l'exclut du balayage.

**Une seule instruction, et pas un SELECT puis un INSERT.** Entre les deux, deux dépôts
concurrents sur la même clé passeraient tous les deux — la skill PostgreSQL le dit, et
l'index unique sur `cle` transformerait la course en violation de contrainte qui avorte la
transaction du lot entier. `ON CONFLICT` laisse la base trancher.

**Ce qui s'est passé est MESURÉ, pas déduit du fait que le code a tourné** : la CTE `avant`
lit l'état d'avant l'écriture, sur le même instantané, et c'est elle qui dit si la base a
bougé. C'est la leçon du 02/11/2026 — une opération idempotente ne sait pas, par son texte,
si elle a agi.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from environnement.storages.ddl import quoted
from environnement.storages.model import StorageTable

MANUAL_ORIGIN = "manuel"
IMPORT_ORIGIN = "import"


class ObjectsDb(Protocol):
    async def fetchrow(self, query: str, *args: Any) -> Any: ...


@dataclass(frozen=True)
class WriteResult:
    """Ce que la base a fait. `refused` : la ligne existante est d'origine manuelle."""

    created: bool
    changed: bool
    refused: bool

    @property
    def written(self) -> bool:
        return self.created or self.changed


def _statement(table: StorageTable) -> str:
    """L'instruction d'écriture d'un objet. Les identités sont CITÉES, jamais concaténées.

    `quoted` refuse ce qui n'est pas un nom : le schéma et la table viennent d'un
    paramétrage venu du réseau, et PostgreSQL n'a pas de requête paramétrée pour une
    identité. C'est la même barrière que celle du DDL, au même endroit.
    """
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    # S608 signale l'assemblage, à juste titre : PostgreSQL n'a pas de requête paramétrée
    # pour une identité. Ce qui tient, et qui est tout ce qui tient : les SEULES valeurs
    # interpolées sont `cible`, passée par `quoted` — qui REFUSE ce qui n'est pas un nom
    # —, et deux littéraux écrits dans ce fichier. La clé, l'objet, l'empreinte, l'instant
    # et la version partent en paramètres. Le `noqa` porte sur l'assemblage, pas sur la
    # provenance.
    return f"""
WITH avant AS (
    SELECT empreinte, origine FROM {cible} WHERE cle = $1
), ecriture AS (
    INSERT INTO {cible} (cle, objet, empreinte, origine, vu_le, modifie_le, version_modele)
    VALUES ($1, $2::jsonb, $3, '{IMPORT_ORIGIN}', $4, $4, $5)
    ON CONFLICT (cle) DO UPDATE SET
        vu_le = excluded.vu_le,
        objet = CASE
            WHEN {cible}.empreinte = excluded.empreinte THEN {cible}.objet
            ELSE excluded.objet END,
        empreinte = excluded.empreinte,
        modifie_le = CASE
            WHEN {cible}.empreinte = excluded.empreinte THEN {cible}.modifie_le
            ELSE excluded.modifie_le END,
        version_modele = excluded.version_modele
    WHERE {cible}.origine = '{IMPORT_ORIGIN}'
    RETURNING 1 AS pose
)
SELECT (SELECT origine FROM avant) AS origine_avant,
       (SELECT empreinte FROM avant) AS empreinte_avant,
       (SELECT count(*) FROM ecriture) AS posees
"""  # noqa: S608


async def db_write_object(
    db: ObjectsDb,
    table: StorageTable,
    *,
    key: str,
    objet: Any,
    empreinte: bytes,
    now: datetime,
    model_version: int,
) -> WriteResult:
    """Écrit l'objet et rend ce que la base a fait de lui."""
    row = await db.fetchrow(
        _statement(table),
        key,
        json.dumps(objet, ensure_ascii=False),
        empreinte,
        now,
        model_version,
    )
    origine_avant = row["origine_avant"]
    if origine_avant == MANUAL_ORIGIN:
        # `posees` vaut alors zéro : la clause WHERE du DO UPDATE a écarté la ligne, et
        # rien n'a été touché — pas même `vu_le`, ce qui est exactement voulu.
        return WriteResult(created=False, changed=False, refused=True)
    if origine_avant is None:
        return WriteResult(created=True, changed=True, refused=False)
    change = bytes(row["empreinte_avant"] or b"") != empreinte
    return WriteResult(created=False, changed=change, refused=False)
