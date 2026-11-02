"""Traduire des critères de recherche en SQL, sur les colonnes que le storage déclare.

Module PUR, et c'est ce qui permet de l'éprouver entièrement : ce qu'il produit
s'exécute sur la base de l'environnement.

**Les valeurs sont PARAMÉTRÉES, les colonnes sont VALIDÉES.** Les deux, parce que les
deux viennent de l'appelant et qu'aucun des deux mécanismes ne couvre l'autre : une
valeur ne peut pas entrer dans le texte de la requête, et un nom de colonne ne peut pas
être paramétré — il est donc comparé à la liste de ce que le storage déclare, et refusé
sinon. Pas de repli sur un parcours de table : un filtre sur une propriété non déclarée
est une erreur d'appel, pas une requête lente.
"""

from __future__ import annotations

from dataclasses import dataclass

from environnement.storages.ddl import quoted
from environnement.storages.model import StorageTable

# Taille de page par défaut, et son plafond. Bornée des deux côtés : sans plafond, un
# appelant demanderait la table entière en une fois.
PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

# Les opérateurs offerts, et leur SQL. La liste est FERMÉE : c'est elle qui fait qu'aucun
# fragment venu de l'appelant n'entre dans la requête.
#
# `prefixe` passe par `like`, et ses jokers sont neutralisés dans la VALEUR, par la
# contre-oblique que `like` prend par défaut pour échappement. Sans cela, un « % »
# écrit par l'appelant rendrait autre chose que le préfixe qu'il a demandé.
OPERATORS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "ge": ">=",
    "lt": "<",
    "le": "<=",
    "prefixe": "like",
}
# La colonne de la clé fonctionnelle est filtrable comme les autres : c'est la première
# chose qu'on cherche dans un storage, et elle porte déjà un index unique.
KEY_COLUMN = "cle"


class FilterError(ValueError):
    """Un critère qu'on refuse, et ce qu'il visait. Nommé : le refus doit se lire."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Criterion:
    column: str
    operator: str
    value: str


@dataclass(frozen=True)
class Query:
    sql: str
    count_sql: str
    values: tuple[object, ...]


def parse_criterion(raw: str) -> Criterion:
    """« colonne:operateur:valeur ». La valeur peut contenir des « : »."""
    parts = raw.split(":", 2)
    if len(parts) != 3 or not parts[0] or not parts[1]:
        raise FilterError("critere_malforme", raw)
    column, operator, value = parts
    if operator not in OPERATORS:
        raise FilterError("operateur_inconnu", operator)
    return Criterion(column, operator, value)


def build(
    table: StorageTable,
    criteria: list[Criterion],
    *,
    sort: str | None = None,
    descending: bool = False,
    page: int = 1,
    page_size: int = PAGE_SIZE,
) -> Query:
    """La requête de recherche, et celle du compte, sur la même clause de filtre."""
    types = {p.column: p.sql_type for p in table.projections} | {KEY_COLUMN: "text"}
    filtrables = set(types)
    clauses: list[str] = []
    values: list[object] = []
    for criterion in criteria:
        if criterion.column not in filtrables:
            # Nommée, pour que l'appelant sache laquelle : « un critère invalide » le
            # laisserait chercher lequel parmi trois.
            raise FilterError("propriete_non_filtrable", criterion.column)
        if criterion.operator == "prefixe" and types[criterion.column] != "text":
            # `like` ne s'applique pas à un nombre ni à un booléen : PostgreSQL
            # refuserait la requête, et un refus nommé ici dit laquelle des deux
            # choses est fausse — le critère, pas la base.
            raise FilterError("prefixe_sur_valeur_non_textuelle", criterion.column)
        values.append(_value(criterion))
        clauses.append(f"{quoted(criterion.column)} {OPERATORS[criterion.operator]} ${len(values)}")
    if sort is not None and sort not in filtrables:
        raise FilterError("propriete_non_triable", sort)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    cible = f"{quoted(table.schema)}.{quoted(table.table)}"
    # `id` TOUJOURS en dernier critère de tri : il rend l'ordre total, et sans cela deux
    # pages consécutives peuvent se recouvrir ou omettre une ligne dès que deux objets
    # portent la même valeur triée.
    sens = "DESC" if descending else "ASC"
    ordre = f"{quoted(sort)} {sens}, " if sort is not None else ""
    taille = min(max(page_size, 1), MAX_PAGE_SIZE)
    saut = (max(page, 1) - 1) * taille
    colonnes = ", ".join(
        [quoted("cle"), quoted("objet"), quoted("vu_le"), quoted("modifie_le"), quoted("origine")]
        + [quoted(p.column) for p in table.projections]
    )
    # S608 signale l'assemblage, à juste titre : il n'existe pas de requête
    # paramétrée pour un NOM. Ce qui tient, et qui est vérifié par les tests de ce
    # module : tout fragment interpolé est soit passé par `quoted` — donc comparé au
    # motif des noms et refusé sinon —, soit un entier calculé ici ; et toute VALEUR
    # venue de l'appelant part en paramètre. Le `noqa` porte sur l'assemblage, pas sur
    # la provenance.
    fin = f" ORDER BY {ordre}{quoted('id')} {sens} LIMIT {taille} OFFSET {saut}"
    sql = f"SELECT {colonnes} FROM {cible}{where}{fin}"  # noqa: S608
    compte = f"SELECT count(*) FROM {cible}{where}"  # noqa: S608
    return Query(sql=sql, count_sql=compte, values=tuple(values))


def _value(criterion: Criterion) -> object:
    if criterion.operator != "prefixe":
        return criterion.value
    # Les jokers de `like` sont neutralisés : on cherche le préfixe demandé, pas le motif
    # que la valeur dessine.
    echappe = criterion.value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{echappe}%"
