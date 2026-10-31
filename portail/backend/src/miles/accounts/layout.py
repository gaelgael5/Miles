from __future__ import annotations

import json
from dataclasses import dataclass

from miles.datamodels.grammar import ModelSyntaxError, load_yaml

# La référence de compte d'une branche (story a3ece1e9) : LE stockage dont les objets
# sont les comptes associés aux devices. Un fichier à la racine, comme les storages et
# les sources — et un seul : une branche a UNE référence de compte, pas une liste.
ROOT = "comptes"
PATH = f"{ROOT}/reference.yaml"
# Volontairement ouvert : la story 918fc940 y ajoutera les lignes d'identification
# (message, champ comparé, canal, destination). Elle AJOUTE des clés, elle ne remplace
# pas le fichier — d'où un jeu de clés connues plutôt qu'une clé unique en dur.
KNOWN_KEYS = frozenset({"storage"})


@dataclass(frozen=True)
class AccountReference:
    # Le nom d'un storage de la branche, et rien d'autre. Le MODÈLE n'est pas ici : le
    # storage le déclare déjà (`modele:`), et le recopier ferait une seconde source de
    # vérité qui dériverait le jour où le storage change de modèle. C'est la correction
    # de Gael du 31/10/2026 : « c'est le stockage que l'on déclare dans la Configuration
    # donc c'est juste une liste déroulante ».
    storage: str


@dataclass(frozen=True)
class ReferenceProblem:
    """Ce qui cloche dans le dépôt, nommé : le fichier, le code, et sur quoi il porte.

    Pas une exception : une branche dont le fichier est fautif se LIT quand même, et
    l'écran doit montrer le réglage en défaut plutôt que de prétendre qu'il n'y en a pas
    (critères 8 et 9).
    """

    path: str
    code: str
    detail: str | None = None


def reference_text(doc: AccountReference) -> str:
    # Valeur écrite en chaîne JSON, qui est aussi une chaîne YAML : un nom de storage
    # reste simple, mais la règle vaut pour tout ce que ce fichier portera ensuite.
    return f"storage: {json.dumps(doc.storage, ensure_ascii=False)}\n"


def read_reference(text: str) -> AccountReference | None:
    """La référence lue, ou None si le contenu n'en a pas la forme.

    Un fichier ABSENT ne passe pas par ici : c'est `None` côté appelant, et ce n'est pas
    une erreur (critère 6). Ici, `None` veut dire « il y a un fichier, et il est fautif ».
    """
    try:
        data = load_yaml(text)
    except ModelSyntaxError:
        return None
    if not isinstance(data, dict) or set(map(str, data)) - KNOWN_KEYS:
        return None
    storage = data.get("storage")
    if not isinstance(storage, str) or not storage.strip():
        return None
    return AccountReference(storage.strip())
