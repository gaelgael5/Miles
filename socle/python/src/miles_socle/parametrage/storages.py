"""Déclaration d'un storage, telle qu'elle est écrite dans le paramétrage.

Un storage (story 844f15ad) : une collection d'objets JSON stockés en base, son modèle,
sa clé fonctionnelle et ce sur quoi on pourra la filtrer. Un fichier par storage, à la
racine comme les sources et les chaînes : le dépôt est déjà propre à une application.

Deux notions distinctes de la source de données (Gael, 24/10/2026) : un storage existe
sans source — on y écrira par API ou par MCP —, et la source ne fait que le désigner.

**Extrait au socle le 02/11/2026**, deuxième usage : le module d'environnement lit ces
mêmes fichiers dans la version qu'il héberge, pour en matérialiser les tables. Seule la
LECTURE est ici. L'écriture (`storage_text`) et le diagnostic de saisie restent au module
de paramétrage : ils supposent la branche, le registre des modèles et le parseur de
jpath du moteur, dont un consommateur n'a que faire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from miles_socle.parametrage.yaml_read import ParametrageSyntaxError, load_yaml

ROOT = "storages"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\.yaml$")
_KEYS = {"nom", "libelle", "modele", "cle", "index", "indexables", "peremption"}
# Un index porte de 1 à 3 colonnes (Gael, 24/10/2026). Le plafond est une décision, pas
# une limite technique : au-delà, un index composite ne sert plus les filtres attendus et
# coûte en écriture ce qu'il ne rend pas en lecture.
MAX_COLUMNS = 3


@dataclass(frozen=True)
class Index:
    """Un index additionnel : son nom, et les colonnes qu'il couvre, dans l'ordre.

    L'ordre compte — c'est celui d'un index composite : il sert les filtres sur la
    première colonne, puis sur les deux premières, etc. Le changer change ce qu'il sert.
    """

    # Identifiant interne, déclaré et non calculé : un `crc32` des colonnes aurait des
    # collisions, et elles seraient silencieuses — deux index sous la même clé, sans
    # erreur visible. Un nom déclaré est aussi stable au renommage d'une colonne.
    name: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Expiry:
    """Une règle de péremption : l'objet sort quand sa propriété plus le délai est passée.

    Déclarée par l'administrateur (Gael, 09/11/2026), et donc dans git : `git revert`
    défait une règle de suppression avec le commit qui l'a posée.

    La propriété désigne une colonne d'index DÉCLARÉE du même storage, et c'est ce qui
    rend la règle évaluable par un filtre indexé plutôt que par un parcours de table —
    l'exigence se vérifie à la saisie, où le modèle est lisible.
    """

    property: str
    # En jours, et le nom le dit : dériver la valeur d'une borne ne dit rien de son unité.
    # Pas de défaut — une règle sans délai supprimerait dès la date atteinte, et ce n'est
    # jamais ce que quelqu'un a voulu écrire sans l'écrire.
    days: int


@dataclass(frozen=True)
class StorageDoc:
    # Identifiant : il nomme le fichier, donc contraint à ce qui fait un nom de fichier.
    # Il se DÉDUIT du libellé à la création (comme un contrat ou une chaîne) : on ne fait
    # pas saisir un slug à la main pour se le voir refuser ensuite.
    name: str
    # Ce que la personne a écrit, et ce que les écrans affichent.
    label: str
    # « shared/site » ou « <domaine>/site » : le modèle des objets stockés.
    model: str
    # Jpath évalués sur l'objet STOCKÉ, et non sur un document source : une collection
    # alimentée par API directe n'a pas de document source (Gael, 24/10/2026).
    keys: tuple[str, ...]
    indexes: tuple[Index, ...]
    # Vide par défaut : un storage sans règle ne se nettoie pas, et un paramétrage déjà
    # écrit ne doit pas se mettre à supprimer parce qu'une version l'a traversé.
    expiries: tuple[Expiry, ...] = ()


def storage_path(name: str) -> str:
    return f"{ROOT}/{name}.yaml"


def names_in(paths: list[str]) -> list[str]:
    return sorted(m["name"] for m in map(_FILE_RE.match, paths) if m is not None)


def read_storage(text: str | None) -> StorageDoc | None:
    """Déclaration lue, ou None si le fichier est absent ou n'en a pas la forme."""
    try:
        data = load_yaml(text) if text is not None else None
    except ParametrageSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - _KEYS:
        return None
    keys = data.get("cle")
    if not isinstance(keys, list):
        return None
    indexes = _indexes(data)
    if indexes is None:
        return None
    try:
        return StorageDoc(
            _text(data.get("nom")),
            _text(data.get("libelle")),
            _text(data.get("modele")),
            tuple(_text(k) for k in keys),
            indexes,
            _expiries(data.get("peremption")),
        )
    except (TypeError, AttributeError):
        return None


def _expiries(raw: object) -> tuple[Expiry, ...]:
    """Les règles de péremption déclarées. Absentes : aucune.

    Une règle mal formée fait refuser la déclaration ENTIÈRE plutôt que d'être ignorée :
    une règle de suppression qu'on écarte en silence laisse croire qu'elle protège, et
    c'est l'inverse d'un repli sûr.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TypeError
    return tuple(_one_expiry(r) for r in raw)


def _one_expiry(raw: object) -> Expiry:
    if not isinstance(raw, dict) or set(map(str, raw)) - {"propriete", "delai_jours"}:
        raise TypeError
    return Expiry(_text(raw.get("propriete")), _days(raw.get("delai_jours")))


def _days(value: object) -> int:
    # Un booléen est un entier en Python, jamais un délai. L'ÉTENDUE (au moins un jour)
    # se juge à la saisie, où l'on sait le dire à qui écrit : ici on ne lit que la forme.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _indexes(data: dict[str, object]) -> tuple[Index, ...] | None:
    """Les index déclarés, l'ancienne forme `indexables` comprise.

    Avant le 24/10/2026 un index couvrait UNE propriété (`indexables: [{nom, jpath}]`).
    La conversion vers un index à une colonne est exacte et sans perte : on la fait, au
    lieu de rendre illisible une déclaration déjà écrite. Ce n'est pas un repli
    silencieux — la forme convertie est réécrite dès le premier enregistrement.
    """
    declared, legacy = data.get("index"), data.get("indexables")
    if declared is not None and legacy is not None:
        # Les deux formes à la fois : on ne devine pas laquelle fait foi.
        return None
    try:
        if legacy is not None:
            if not isinstance(legacy, list):
                return None
            return tuple(Index(_text(i.get("nom")), (_text(i.get("jpath")),)) for i in legacy)
        if declared is None:
            return ()
        if not isinstance(declared, list):
            return None
        return tuple(_one_index(i) for i in declared)
    except (TypeError, AttributeError):
        return None


def _one_index(raw: object) -> Index:
    columns = raw.get("colonnes") if isinstance(raw, dict) else None
    if not isinstance(columns, list):
        raise TypeError
    name = raw.get("nom") if isinstance(raw, dict) else None
    return Index(_text(name), tuple(_text(c) for c in columns))


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value
