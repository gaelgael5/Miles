from __future__ import annotations

import json
from dataclasses import dataclass

from miles.datamodels.grammar import ModelSyntaxError, load_yaml

# La référence de compte d'une branche (story a3ece1e9) : LE stockage dont les objets
# sont les comptes associés aux devices. Un fichier à la racine, comme les storages et
# les sources — et un seul : une branche a UNE référence de compte, pas une liste.
ROOT = "comptes"
PATH = f"{ROOT}/reference.yaml"
KNOWN_KEYS = frozenset({"storage", "envoi"})
_DELIVERY_KEYS = frozenset({"mode", "champ"})

# Les modes d'envoi du code d'enregistrement, dans l'ordre où Gael les a nommés le
# 31/10/2026. La liste est FIGÉE ici et non déduite de ce qui est servi : elle entre
# dans le fichier de la branche, et la fixer maintenant évite d'avoir à migrer des
# fichiers le jour où un mode de plus est branché.
MODES = ("whatsapp", "viber", "signal", "sms", "email")
# Ce qui est réellement construit : « pour le moment on implémentera que le mail »
# (Gael, 31/10/2026). Les autres sont REFUSÉS à l'enregistrement plutôt qu'acceptés
# sans effet — une branche qui porterait « viber » laisserait croire qu'un code part.
SERVED_MODES = ("email",)


@dataclass(frozen=True)
class Delivery:
    """Par quel mode part le code d'enregistrement, et vers quel champ du compte."""

    mode: str
    # Jpath évalué sur le COMPTE stocké, désignant l'adresse d'envoi. Choisi dans les
    # propriétés du modèle, jamais saisi librement : un chemin tapé à la main désignerait
    # une propriété qui n'existe pas, et l'erreur n'apparaîtrait qu'au premier terminal.
    field: str


@dataclass(frozen=True)
class AccountReference:
    # Le nom d'un storage de la branche. Le MODÈLE n'est pas ici : le storage le déclare
    # déjà (`modele:`), et le recopier ferait une seconde source de vérité qui dériverait
    # le jour où le storage change de modèle. C'est la correction de Gael du 31/10/2026 :
    # « c'est le stockage que l'on déclare dans la Configuration donc c'est juste une
    # liste déroulante ».
    storage: str
    # None : le stockage est désigné, l'envoi ne l'est pas encore. Ce n'est pas une
    # erreur — c'est l'état d'une référence qu'on vient de poser.
    delivery: Delivery | None = None


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
    # Valeurs écrites en chaînes JSON, qui sont aussi des chaînes YAML : un jpath porte
    # des « $ », « [ » et « : » qui changeraient la structure du fichier non échappés.
    def q(value: str) -> str:
        return json.dumps(value, ensure_ascii=False)

    lines = [f"storage: {q(doc.storage)}"]
    if doc.delivery is not None:
        lines += [
            "envoi:",
            f"  mode: {q(doc.delivery.mode)}",
            f"  champ: {q(doc.delivery.field)}",
        ]
    return "\n".join(lines) + "\n"


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
    raw = data.get("envoi")
    if raw is None:
        return AccountReference(storage.strip())
    delivery = _delivery(raw)
    # Un bloc `envoi` présent mais fautif rend le fichier ENTIER illisible, plutôt que de
    # rendre la référence sans lui : sinon l'écran montrerait un stockage sans envoi,
    # c'est-à-dire un réglage qui a l'air inachevé là où il est cassé.
    return None if delivery is None else AccountReference(storage.strip(), delivery)


def _delivery(raw: object) -> Delivery | None:
    if not isinstance(raw, dict) or set(map(str, raw)) - _DELIVERY_KEYS:
        return None
    mode, field = raw.get("mode"), raw.get("champ")
    if not isinstance(mode, str) or not isinstance(field, str):
        return None
    mode, field = mode.strip(), field.strip()
    # Le mode est validé ICI, à la lecture : un fichier écrit à la main sur un mode qui
    # n'existe pas n'est pas un réglage incomplet, c'est un fichier fautif, et il doit
    # se dire comme tel. La LISTE fait foi, pas ce qui est servi : un fichier préparé
    # pour « viber » reste lisible, il sera seulement refusé à l'enregistrement.
    if mode not in MODES or not field:
        return None
    return Delivery(mode, field)
