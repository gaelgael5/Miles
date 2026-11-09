"""Appliquer les règles de nettoyage d'un storage : SUPPRIMER, et laisser la trace. `45543845`.

Deux règles, et elles ne lisent pas la même chose :

- **absents de l'import depuis N jours** — la marque qu'un import complet a posée
  (`absence.py`) a plus de N jours. `N` est déclaré sur l'ENTRÉE de source, parce que
  « absent de l'import » n'a de sens que relativement à un dépôt qui prétend porter
  l'image complète ;
- **péremption** — la propriété datée que l'objet PORTE, plus son délai, est passée. Elle
  est déclarée sur le STORAGE : elle vaut quelle que soit la source, et même sans source.

**Le déclenchement est la fin d'un import `traite`, et rien d'autre** (Gael, 09/11/2026 :
« le déclenchement du nettoyage se traite à la fin de l'import fichier »). Aucun
ordonnanceur n'est ajouté, et la conséquence est assumée : un storage qui ne reçoit plus
d'import ne se nettoie plus. Gael l'a tranché le même jour — « on ne traite pas le sujet
d'un storage qui cesse de recevoir des imports ». Ne pas ajouter de déclencheur d'hôte ici
sans le lui demander : un nettoyage qui tourne sans que personne ne dépose rien est un
dispositif qui supprime sans que personne ne regarde.

**Ce module ne tient jamais le lot en mémoire** : il balaie par fenêtres bornées, du plus
ancien au plus récent selon la colonne de la règle, et chaque fenêtre est supprimée avec
ses events dans UNE transaction courte. Un export réel compte 168 775 items.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from miles_socle.events.journal import db_write_events
from miles_socle.events.model import NewEvent, ObjectRef
from miles_socle.parametrage.sources import SourceDoc

from environnement.ingestion.writeback import Processing
from environnement.storages.ddl import quoted
from environnement.storages.model import ABSENCE_COLUMN, ExpiryRule, StorageTable

log = structlog.get_logger(__name__)

OBJECT_REMOVED_EVENT = "environment.storage_object_removed"
EVENT_TYPES = frozenset({OBJECT_REMOVED_EVENT})

# Les deux règles, nommées : l'event dit LAQUELLE a désigné l'objet, et « supprimé par le
# nettoyage » n'aurait pas permis de rattraper une règle écrite de travers.
KIND_MISSING = "absents"
KIND_EXPIRY = "peremption"

# Combien d'items une fenêtre emporte. Cent, comme la fenêtre de fusion : la transaction
# reste courte, et les events de la fenêtre partent en trois instructions quel que soit
# leur nombre (`db_write_events`). Plus large, on rallonge une transaction qui verrouille
# des lignes de la table que l'import vient d'écrire ; plus étroite, on paie un
# aller-retour pour dix lignes.
REMOVAL_WINDOW = 100

# La FORME qu'une valeur doit avoir pour être comparée au seuil : ISO-8601 étendu, année
# en 19xx ou 20xx. Appliquée EN SQL, sur les candidats du range, et c'est une garde
# mesurée — le ticket de déclaration l'a établi : une valeur non datée trie au-dessus du
# seuil (donc survit), SAUF si elle commence par un chiffre inférieur à 2, et celle-là
# serait supprimée à tort. Ce motif l'écarte sans convertir la colonne : un `~` sur du
# texte ne peut pas échouer, là où un `::date` ferait tomber la requête ENTIÈRE sur une
# seule valeur inconvertible.
#
# Il dit la forme, jamais la validité : « 2026-02-30 » le satisfait. C'est pourquoi chaque
# candidat est RELU en Python avant d'être supprimé (`removable`).
ISO_DATE_RE = r"^(19|20)[0-9]{2}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"


@dataclass(frozen=True)
class CleanupRule:
    """Une règle prête à sélectionner : sa colonne, son délai, et ce qu'elle désigne.

    `path` et `source` ne sont là que pour se DIRE — dans l'event, dans l'écran, dans un
    refus. Une trace qui nommerait `fin_activite` ou « péremption » tout court enverrait
    chercher laquelle des règles d'un storage a supprimé l'objet.
    """

    kind: str
    column: str
    days: int
    # Le chemin déclaré de la propriété, pour une règle de péremption ; nul pour les absents.
    path: str | None = None
    # La source dont l'entrée porte la règle des absents ; nulle pour une péremption.
    source: str | None = None

    @property
    def dated(self) -> bool:
        """La colonne est-elle du TEXTE à relire comme une date ?

        `absent_depuis` est une vraie `timestamptz` posée par nous : il n'y a rien à
        valider. Une colonne projetée reste `text` à dessein (story `c705e801`), et c'est
        elle qui demande les deux gardes — le motif en SQL, la relecture en Python.
        """
        return self.kind == KIND_EXPIRY


def missing_rule(days: int, source: str) -> CleanupRule:
    return CleanupRule(KIND_MISSING, ABSENCE_COLUMN, days, source=source)


def expiry_rule(rule: ExpiryRule) -> CleanupRule:
    return CleanupRule(KIND_EXPIRY, rule.column, rule.days, path=rule.path)


def rules_of(table: StorageTable, sources: list[SourceDoc]) -> list[CleanupRule]:
    """Toutes les règles qui portent sur ce storage : celles des entrées, puis la péremption.

    Sert la RESTITUTION, qui regarde un storage sans passer par un import. La fin d'un
    import, elle, n'emprunte que la règle de SON entrée (`fileimport._rules`) : plusieurs
    sources peuvent alimenter le même storage, et c'est le dépôt qui dit laquelle vient de
    prétendre porter l'image complète.

    Seules les entrées qui offrent le mode `fichier` portent une règle d'absents — l'autre
    cas est refusé à la saisie —, et une source qui en déclare plusieurs ne donne qu'une
    règle : la plus COURTE. C'est celle qui décide en pratique, puisque le premier import
    qui l'atteint supprime ; afficher les deux ferait croire qu'un item survit jusqu'au
    délai le plus long.
    """
    par_source: dict[str, int] = {}
    for doc in sources:
        if doc.storage != table.storage:
            continue
        for entry in doc.entries:
            jours = entry.missing_removed_after_days
            if not entry.modes.file or jours is None:
                continue
            connu = par_source.get(doc.name)
            par_source[doc.name] = jours if connu is None else min(connu, jours)
    regles = [missing_rule(jours, source) for source, jours in sorted(par_source.items())]
    return regles + [expiry_rule(rule) for rule in table.expiries]


def rule_id(rule: CleanupRule) -> str:
    """Le nom par lequel une règle se désigne dans une URL.

    Dérivé de ce que la règle EST — son genre et ce qu'elle nomme — et non de son rang :
    un rang changerait de sens dès qu'une règle est ajoutée devant, et une page mise en
    favori montrerait une autre règle que celle qu'on avait regardée.
    """
    return f"{rule.kind}:{rule.path or rule.source}"


def threshold(rule: CleanupRule, now: datetime) -> Any:
    """Le seuil : « maintenant moins le délai ». **On déplace le seuil, jamais la colonne.**

    Arbitrage de Gael du 09/11/2026 (« on déplace le seuil »), et deux dégâts distincts
    l'imposent : un `(colonne)::date` perd l'index déclaré, et il fait échouer la requête
    entière sur une seule valeur non convertible — c'est-à-dire supprime la seule chose
    qui pouvait signaler la donnée fautive.

    Rendu en ISO-8601 pour une colonne projetée : l'ordre lexicographique d'un ISO-8601
    EST l'ordre chronologique, prouvé en test par la story `c705e801`, changement d'année
    compris. Rendu en `datetime` pour `absent_depuis`, qui est une vraie date en base.
    """
    moment = now - timedelta(days=rule.days)
    return moment if not rule.dated else moment.isoformat()


def _where(rule: CleanupRule) -> str:
    """La clause de sélection d'une règle, sans son ordre ni ses bornes.

    L'opérateur n'est pas le même, et ce n'est pas une inattention : la marque d'absence
    doit être « plus vieille que N jours » (`<`), tandis que la péremption se lit
    « propriété + délai est passée », donc antérieure OU ÉGALE à maintenant (`<=`) —
    lecture retenue des mots de Gael, écrite dans le ticket.
    """
    colonne = f"c.{quoted(rule.column)}"
    comparaison = "<=" if rule.dated else "<"
    clauses = [f"{colonne} IS NOT NULL", f"{colonne} {comparaison} $1"]
    if rule.dated:
        clauses.append(f"{colonne} ~ '{ISO_DATE_RE}'")
    return " AND ".join(clauses)


def _cast(rule: CleanupRule) -> str:
    return "text" if rule.dated else "timestamptz"


def scan_statement(table: StorageTable, rule: CleanupRule) -> str:
    """Une fenêtre de candidats, APRÈS le curseur, dans l'ordre de la colonne de la règle.

    **L'ordre est celui de la colonne, et c'est ce qui emprunte l'index déclaré** : une
    règle de péremption porte forcément sur une colonne d'index (exigé à la saisie), donc
    « plage sur la colonne + ordre sur la colonne » est exactement ce que cet index sert.
    Trier sur `cle` aurait fait choisir l'index de la clé et filtrer le reste, c'est-à-dire
    parcourir la table. La règle des absents n'a pas d'index sur `absent_depuis` et n'en
    demande pas : elle tourne à la fin d'un import qui vient de traverser la table.

    **Un CURSEUR et non un `OFFSET`** : on supprime ce qu'on vient de lire, donc les rangs
    se décalent sous nos pieds. Le curseur avance aussi par-dessus les valeurs que la
    relecture écarte (`_dated`), là où une reprise depuis le début les relirait sans fin.
    """
    return f"""
        SELECT c.id, c.cle, c.{quoted(rule.column)} AS valeur
        FROM {_target(table)} AS c
        WHERE {_where(rule)}
          AND ($2::{_cast(rule)} IS NULL OR (c.{quoted(rule.column)}, c.cle) > ($2, $3))
        ORDER BY c.{quoted(rule.column)}, c.cle
        LIMIT $4
    """  # noqa: S608


def page_statement(table: StorageTable, rule: CleanupRule) -> str:
    """La page de ce qu'une règle désignerait, pour la montrer SANS rien supprimer.

    Par rang et non par curseur, parce qu'un écran pagine : rien n'est supprimé pendant
    qu'on regarde, donc les rangs ne bougent pas sous la requête. L'ordre est total
    (colonne, clé, id) : sans quoi deux pages consécutives se recouvrent dès que deux
    objets portent la même valeur.
    """
    return f"""
        SELECT c.cle, c.objet, c.vu_le, c.{quoted(ABSENCE_COLUMN)} AS absent_depuis,
               c.{quoted(rule.column)} AS valeur
        FROM {_target(table)} AS c
        WHERE {_where(rule)}
        ORDER BY c.{quoted(rule.column)}, c.cle, c.id
        LIMIT $2 OFFSET $3
    """  # noqa: S608


def count_statement(table: StorageTable, rule: CleanupRule) -> str:
    """Combien d'items la règle désigne. Sur la MÊME clause que la page."""
    return f"SELECT count(*) FROM {_target(table)} AS c WHERE {_where(rule)}"  # noqa: S608


def delete_statement(table: StorageTable) -> str:
    """La suppression d'une fenêtre, par identifiant, qui REND l'objet entier.

    Rendu par la suppression elle-même et non relu avant : c'est l'objet tel qu'il était
    au moment de sortir qui part dans l'event, et une lecture antérieure aurait pu rendre
    une version que l'écriture manuelle d'entre-temps a remplacée.
    """
    return f"""
        DELETE FROM {_target(table)} AS c
        WHERE c.id = ANY($1::bigint[])
        RETURNING c.cle, c.objet
    """  # noqa: S608


def _target(table: StorageTable) -> str:
    # S608 signale l'assemblage, à juste titre : il n'existe pas de requête paramétrée
    # pour un NOM. Les seules valeurs interpolées de ce module sont des identités passées
    # par `quoted` — qui REFUSE ce qui n'est pas un nom — et le motif ISO, littéral de ce
    # fichier. Le seuil, le curseur, les bornes et les identifiants partent en paramètres.
    return f"{quoted(table.schema)}.{quoted(table.table)}"


async def db_remove_designated(
    processing: Processing,
    table: StorageTable,
    rules: list[CleanupRule],
    *,
    now: datetime,
) -> int | None:
    """Supprime ce que les règles désignent, trace chaque suppression, rend le compte.

    **Rend `None` sans rien supprimer si une règle de péremption n'est plus évaluable** :
    sa propriété a disparu du modèle ou n'est plus projetée. Fail closed, et il porte sur
    TOUT le storage — y compris les autres règles, dont on ne sait pas si elles étaient
    censées porter seules (critère 10). Une règle de suppression qu'on ne sait plus
    évaluer ne se rabat pas sur une approximation.

    `None` et zéro ne disent donc pas la même chose : l'un est un nettoyage refusé,
    l'autre un nettoyage qui n'avait rien à sortir.
    """
    if table.unresolved_expiries:
        log.warning(
            "nettoyage_refuse",
            storage=table.storage,
            proprietes=list(table.unresolved_expiries),
        )
        return None
    if not rules:
        return 0
    total = 0
    for rule in rules:
        total += await _apply(processing, table, rule, now=now)
    return total


async def _apply(
    processing: Processing, table: StorageTable, rule: CleanupRule, *, now: datetime
) -> int:
    """Balaie une règle, fenêtre par fenêtre, jusqu'à l'épuiser."""
    seuil = threshold(rule, now)
    statement = scan_statement(table, rule)
    curseur: tuple[Any, str] | None = None
    supprimes, non_datees, exemple = 0, 0, None
    while True:
        valeur, cle = curseur if curseur is not None else (None, None)
        fenetre = await processing.db.fetch(statement, seuil, valeur, cle, REMOVAL_WINDOW)
        if not fenetre:
            break
        curseur = (fenetre[-1]["valeur"], fenetre[-1]["cle"])
        gardees: list[Any] = []
        ecartees: list[Any] = []
        for row in fenetre:
            (gardees if removable(rule, row["valeur"]) else ecartees).append(row)
        if ecartees:
            non_datees += len(ecartees)
            exemple = exemple or ecartees[0]["cle"]
        if gardees:
            supprimes += await _remove_window(processing, table, rule, gardees)
        if len(fenetre) < REMOVAL_WINDOW:
            break
    if non_datees:
        # DIT, et non tu : ces items ne sont pas supprimés, et personne ne peut deviner
        # qu'une règle de péremption ne les atteint pas. C'est la donnée qu'il faut aller
        # corriger, et l'écran de restitution les montre un par un.
        log.warning(
            "peremption_valeur_non_datee",
            storage=table.storage,
            propriete=rule.path,
            items=non_datees,
            exemple=exemple,
        )
    if supprimes:
        log.info(
            "items_supprimes",
            storage=table.storage,
            regle=rule.kind,
            propriete=rule.path,
            jours=rule.days,
            items=supprimes,
        )
    return supprimes


async def _remove_window(
    processing: Processing, table: StorageTable, rule: CleanupRule, rows: list[Any]
) -> int:
    """Supprime une fenêtre et écrit ses events DANS LA MÊME transaction.

    La même, parce qu'un fait observable sans sa trace est interdit par le système — et
    ici plus qu'ailleurs : une suppression sans trace ne se rattrape pas, c'est l'interdit
    que Gael a posé le premier. Une transaction PAR FENÊTRE et non une pour tout le
    nettoyage : elle verrouille des lignes de la table que l'import vient d'écrire.
    """
    async with processing.db.transaction():
        sorties = await processing.db.fetch(delete_statement(table), [row["id"] for row in rows])
        if sorties:
            await db_write_events(
                processing.db,
                [_event(processing, table, rule, row) for row in sorties],
                processing.catalog,
                processing.now,
            )
    return len(sorties)


def _event(processing: Processing, table: StorageTable, rule: CleanupRule, row: Any) -> NewEvent:
    """L'event d'une suppression : l'objet ENTIER, et la règle qui l'a désigné.

    L'objet entier parce que c'est la seule façon de rattraper une suppression — la ligne
    n'existe plus, et un event qui n'en garderait que la clé ne permettrait pas de la
    reposer. C'est cohérent avec « un event par objet écrit » (02/11/2026) et avec le
    partitionnement du journal à la journée, qui la rend tenable.
    """
    return NewEvent(
        OBJECT_REMOVED_EVENT,
        (ObjectRef(table.storage, row["cle"]),),
        processing.author,
        {
            "storage": table.storage,
            "model": table.model,
            "ingestion": processing.ingestion_id,
            "rule": rule.kind,
            "property": rule.path,
            "source": rule.source,
            "days": rule.days,
            "objet": _json(row["objet"]),
        },
    )


def removable(rule: CleanupRule, value: Any) -> bool:
    """L'item sortirait-il vraiment ? C'est-à-dire : la valeur est-elle une date ?

    Relue en Python et pas seulement filtrée en SQL : le motif dit la FORME, et
    « 2026-02-30 » la satisfait sans être une date. Une seule de ces deux gardes aurait
    laissé passer l'un des deux cas, et le prix d'un faux positif est une suppression.
    """
    if not rule.dated:
        return True
    try:
        datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def _json(value: object) -> dict[str, Any]:
    # Une colonne jsonb revient d'asyncpg en CHAÎNE : une leçon du dépôt porte le jour où
    # un test l'a oublié.
    if isinstance(value, str):
        value = json.loads(value)
    return value if isinstance(value, dict) else {}
