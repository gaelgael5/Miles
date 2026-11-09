"""Déclaration d'une source de données, telle qu'elle est écrite dans le paramétrage.

Une source (story 66391afe, refondue le 25/10/2026) : une ENTRÉE de données dans
l'application. Elle dit d'abord OÙ ça va — la donnée cible, c'est-à-dire le storage — et
porte ensuite une ou plusieurs entrées, chacune décrivant par quel moyen la donnée arrive.

**Extrait au socle le 02/11/2026**, deuxième usage : le module d'environnement lit ces
mêmes fichiers dans la version qu'il héberge, pour savoir quels points d'entrée exposer,
quelles méthodes chaque entrée offre, et quelles sources une clé d'API peut ouvrir. Seule
la LECTURE est ici. L'écriture (`source_text`) et le diagnostic de saisie restent au
module de paramétrage : ils supposent la branche, le registre des modèles et le parseur
de jpath du moteur, dont un consommateur n'a que faire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from miles_socle.parametrage.yaml_read import ParametrageSyntaxError, load_yaml

ROOT = "sources"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_FILE_RE = re.compile(rf"^{ROOT}/(?P<name>[^/]+)\.yaml$")
_KEYS = {"nom", "libelle", "storage", "entrees"}
_ENTRY_KEYS = {
    "type",
    "modele_source",
    "chaine",
    "modes",
    "decoupage",
    "transaction_unifiee",
    "lot_ecriture",
    "absents_supprimes_apres_jours",
}
_MODE_KEYS = {"element", "tableau", "fichier"}

# Le seul moyen d'entrée instruit à ce jour. Le type est écrit dans la déclaration plutôt
# que sous-entendu : un second moyen (file de messages) s'ajoutera sans rendre ambiguës
# les déclarations déjà écrites.
WEB = "web"
ENTRY_TYPES = frozenset({WEB})
# Plafond du mode tableau (Gael, 25/10/2026). C'est une décision, pas une limite
# technique : au-delà, un appel unique devient un lot qu'il faut reprendre et suivre,
# et c'est le mode fichier qui le sert.
MAX_BATCH = 200
# Lectures consécutives avant enregistrement, par défaut (Gael, 25/10/2026). Écrire à
# chaque lecture coûte un aller-retour par objet ; cent lectures amortissent l'écriture
# sans retenir assez d'objets pour peser en mémoire.
DEFAULT_WRITE_BATCH = 100


@dataclass(frozen=True)
class EntryModes:
    """Les méthodes exposées par une entrée. Au moins une, sinon elle n'expose rien.

    C'est par ce choix que la taille et le rythme d'une intégration se règlent (Gael,
    02/11/2026) : l'unité et le tableau répondent de façon synchrone, clé par clé ; le
    fichier n'accuse que la prise en charge. Un mode non coché est donc REFUSÉ par le
    point d'entrée, jamais accepté sans effet — ce qui laisserait croire à un dépôt.
    """

    element: bool
    batch: bool
    file: bool


@dataclass(frozen=True)
class Entry:
    kind: str
    # « portée/nom » du modèle qui arrive sur la méthode : il la type.
    source_model: str
    # Slug de la chaîne qui mène du modèle source au modèle du storage.
    chain: str
    modes: EntryModes
    # Où sont les items dans le fichier déposé. Requis par le mode fichier, et par lui
    # seul : les deux autres méthodes reçoivent déjà des objets typés.
    split: str
    # Une seule transaction pour tout l'import, ou une par lot écrit. Ne couvre que
    # l'échec du DÉPÔT : le rejet d'un objet fautif ne fait pas tomber les autres
    # (Gael, 02/11/2026) — chaque objet est indépendant.
    unified_transaction: bool
    # Nombre de lectures consécutives avant enregistrement. Il dit TOUS LES COMBIEN on
    # écrit ; la transaction unifiée dit QUAND on valide. Les deux sont indépendants.
    write_batch: int
    # Délai après lequel un item que cette entrée n'a plus porté est supprimé (Gael,
    # 09/11/2026). `None` : aucune règle, et c'est le défaut — un paramétrage déjà écrit
    # ne se met pas à supprimer.
    #
    # La règle vit sur l'ENTRÉE et non sur le storage parce qu'« absent de l'import » n'a
    # de sens que relativement à un dépôt qui prétend porter l'image complète : plusieurs
    # sources peuvent alimenter le même storage, et un dépôt unitaire ne dit rien de ce
    # qu'il ne contient pas. L'exigence du mode `fichier` se vérifie à la saisie.
    missing_removed_after_days: int | None = None


@dataclass(frozen=True)
class SourceDoc:
    # Identifiant : il nomme le fichier, et se déduit du libellé à la création.
    name: str
    # Ce que la personne a écrit, et ce que les écrans affichent.
    label: str
    # La donnée cible : le storage où les objets atterrissent.
    storage: str
    entries: tuple[Entry, ...]


def source_path(name: str) -> str:
    return f"{ROOT}/{name}.yaml"


def names_in(paths: list[str]) -> list[str]:
    return sorted(m["name"] for m in map(_FILE_RE.match, paths) if m is not None)


def read_source(text: str | None) -> SourceDoc | None:
    """Déclaration lue, ou None si le fichier est absent ou n'en a pas la forme."""
    try:
        data = load_yaml(text) if text is not None else None
    except ParametrageSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - _KEYS:
        return None
    raw = data.get("entrees")
    if raw is not None and not isinstance(raw, list):
        return None
    try:
        return SourceDoc(
            _text(data.get("nom")),
            _text(data.get("libelle")),
            _text(data.get("storage")),
            tuple(_entry(e) for e in (raw or [])),
        )
    except (TypeError, AttributeError):
        return None


def _entry(raw: object) -> Entry:
    if not isinstance(raw, dict) or set(map(str, raw)) - _ENTRY_KEYS:
        raise TypeError
    modes = raw.get("modes")
    if not isinstance(modes, dict) or set(map(str, modes)) - _MODE_KEYS:
        raise TypeError
    return Entry(
        _text(raw.get("type")),
        _text(raw.get("modele_source")),
        _text(raw.get("chaine")),
        EntryModes(
            _flag(modes.get("element")), _flag(modes.get("tableau")), _flag(modes.get("fichier"))
        ),
        _optional_text(raw.get("decoupage")),
        _flag(raw.get("transaction_unifiee")),
        _count(raw.get("lot_ecriture")),
        _optional_count(raw.get("absents_supprimes_apres_jours")),
    )


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError
    return value


def _optional_text(value: object) -> str:
    """Absent : vide. Le découpage ne sert qu'au mode fichier, et le diagnostic de saisie
    l'exige quand ce mode est coché — l'absence se juge là, pas à la lecture du fichier."""
    if value is None:
        return ""
    return _text(value)


def _count(value: object) -> int:
    """Absent : la valeur par défaut. Un booléen n'est pas un entier, même en Python."""
    if value is None:
        return DEFAULT_WRITE_BATCH
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _optional_count(value: object) -> int | None:
    """Absent : aucune règle, et non un délai par défaut.

    Un défaut ferait supprimer dans un paramétrage où personne n'a demandé de
    suppression — l'absence de règle doit rester l'absence de règle. L'ÉTENDUE (au moins
    un jour) se juge à la saisie, où l'on sait le dire à qui écrit.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError
    return value


def _flag(value: object) -> bool:
    # Absent : faux. Un mode et une garantie se déclarent ; ils ne s'inventent pas.
    if value is None:
        return False
    if not isinstance(value, bool):
        raise TypeError
    return value
