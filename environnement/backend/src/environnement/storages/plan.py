"""L'écart entre ce que la base porte et ce que la version déclare, en SQL.

Séparé du service, et pas seulement pour la limite de 300 lignes : ce calcul est PUR —
il prend la forme réelle de la table et la déclaration, et rend des instructions. Il
s'éprouve donc sans base, ce qui est exactement ce qu'on veut d'une décision où une
erreur retire une colonne qu'il fallait garder.

**Ce qui se supprime, et ce qui ne se supprime jamais.** Une colonne DÉRIVÉE se retire
sans perte : elle est une fonction de `objet`, et PostgreSQL la recalcule à l'identique
si on la remet. Une colonne de données, une table, un index posé par quelqu'un d'autre :
on n'y touche pas, et un écart constaté se signale au lieu d'être réparé.
"""

from __future__ import annotations

from environnement.storages.ddl import (
    KEY_INDEX,
    add_column,
    add_fixed_column,
    drop_column,
    drop_index,
    index_name,
    index_statement,
    is_ours,
    key_index,
)
from environnement.storages.model import (
    ADDABLE_COLUMNS,
    FIXED_COLUMNS,
    REFUSAL_TYPE_CHANGE,
    REFUSAL_UNEXPECTED_SHAPE,
    StorageRefusal,
    StorageTable,
)
from environnement.storages.store import ExistingTable


def missing_fixed(existing: ExistingTable) -> str | None:
    """Le nom de la première colonne fixe absente ou mal typée. Nul si la forme tient.

    **Les colonnes d'`ADDABLE_COLUMNS` absentes ne comptent pas ici** : elles ont été
    introduites après que des tables de storage tournaient déjà, et l'alignement les
    AJOUTE. Les compter aurait fait refuser chaque storage en service au premier
    déploiement qui en introduit une — et ce refus-là n'a aucun geste de réparation,
    puisqu'une forme inattendue se signale sans se corriger. Mal TYPÉE, en revanche, reste
    une forme inattendue : la colonne existe et ne porte pas ce qu'on croit.
    """
    for name, sql_type in FIXED_COLUMNS:
        column = existing.column(name)
        if column is None:
            if name in ADDABLE_COLUMNS:
                continue
            return name
        if column.sql_type != sql_type:
            return f"{name}:{column.sql_type}"
    return None


def alignment(
    table: StorageTable, existing: ExistingTable
) -> tuple[list[str], bool] | StorageRefusal:
    """Ce qu'il faut faire pour que la table porte ce que la version déclare."""
    instructions: list[str] = []
    # Les colonnes fixes ajoutables qui manquent, AVANT les colonnes dérivées : la marque
    # d'absence est lue par l'écriture des imports, et une instruction d'alignement qui
    # échouerait plus loin ne doit pas laisser la table sans elle.
    instructions += [
        add_fixed_column(table, name, sql_type)
        for name, sql_type in FIXED_COLUMNS
        if name in ADDABLE_COLUMNS and existing.column(name) is None
    ]
    voulues = {p.column: p for p in table.projections}
    for projection in table.projections:
        column = existing.column(projection.column)
        if column is None:
            instructions.append(add_column(table, projection))
            continue
        if not column.generated:
            # Une colonne de DONNÉES porte ce nom. On ne la remplace pas : elle pourrait
            # porter de la donnée propre, que la dérivation écraserait sans retour.
            return StorageRefusal(table.storage, REFUSAL_UNEXPECTED_SHAPE, projection.column)
        if column.sql_type != projection.sql_type:
            # Changer le type d'une colonne dérivée réécrit la table sous verrou. Le coût
            # n'a pas été mesuré : on s'arrête et on le dit, plutôt que de le payer à
            # l'insu de qui déploie.
            return StorageRefusal(
                table.storage,
                REFUSAL_TYPE_CHANGE,
                f"{projection.column}:{column.sql_type}->{projection.sql_type}",
            )
    for column in existing.columns:
        if column.generated and column.name not in voulues:
            # La version ne la déclare plus. Sans perte : la colonne est une fonction de
            # `objet`, donc la retirer ne retire aucune donnée, et une réintroduction
            # ultérieure retrouve les mêmes valeurs.
            instructions.append(drop_column(table, column.name))
    # Les colonnes ajoutées ou retirées suffisent à dire que la base bouge ; les index
    # manquants aussi, et il faut les compter séparément — une version peut n'ajouter
    # qu'un index sur une colonne déjà là.
    colonnes_bougent = bool(instructions)
    return _indexes(table, existing, instructions, colonnes_bougent)


def _indexes(
    table: StorageTable,
    existing: ExistingTable,
    instructions: list[str],
    colonnes_bougent: bool,
) -> tuple[list[str], bool]:
    """Ce qu'il faut faire des index, en ne créant QUE ce qui manque.

    **On ne crée que les manquants**, et c'est de là que vient l'idempotence : la
        création d'index, elle, ne tolère rien (voir `index_statement`).

        Et un index déclaré dont les COLONNES changent garde son nom : il est refait, pas
        laissé en place. Comparer les seuls noms aurait laissé un index qui n'indexe plus ce
        que la version demande.
    """
    voulus = {index_name(table.table, i.name): i.columns for i in table.indexes}
    voulus[index_name(table.table, KEY_INDEX)] = ("cle",)
    a_refaire = [
        nom
        for nom, colonnes in voulus.items()
        if (porte := existing.index(nom)) is not None and porte.columns != colonnes
    ]
    manquants = [nom for nom in voulus if existing.index(nom) is None]
    retires = [
        item.name
        for item in existing.indexes
        if is_ours(table.table, item.name) and item.name not in voulus
    ]
    # L'ordre compte : on retire avant de reposer, sinon la création bute sur le nom.
    instructions += [drop_index(table.schema, nom) for nom in a_refaire + retires]
    instructions += [
        key_index(table)
        if nom == index_name(table.table, KEY_INDEX)
        else index_statement(table, nom, voulus[nom])
        for nom in manquants + a_refaire
    ]
    return instructions, colonnes_bougent or bool(manquants or a_refaire or retires)
