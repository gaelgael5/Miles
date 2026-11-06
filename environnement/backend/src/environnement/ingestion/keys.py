"""La clé fonctionnelle d'un objet : extraite de l'objet STOCKÉ, par les jpath du storage.

**Sur l'objet stocké, et non sur le document source**, et c'est une décision de Gael du
24/10/2026, écrite dans la déclaration d'un storage : « une collection alimentée par API
directe n'a pas de document source ». Elle AMENDE la story `d680e811`, écrite le 15
octobre, qui demandait l'inverse — une règle d'extraction distincte du template, appliquée
à la source. Les deux ne tiennent pas ensemble : un storage qu'on alimente aussi à la main
ou par MCP doit savoir donner son identité à un objet qui n'est jamais passé par une
source. La conséquence à connaître est que l'identité dépend alors du template : un
template qui cesse de produire la propriété de clé rend les objets suivants inidentifiables
— et c'est un REJET nommé, jamais une clé vide.

Module PUR : il ne touche ni base ni arbre git. C'est voulu — une erreur ici fait écrire un
objet sous l'identité d'un autre, et cela doit s'éprouver sans rien monter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from miles_socle.transform.jpath import path_keys


class KeyNotExtractable(Exception):
    """Aucune valeur pour l'un des jpath de clé : l'objet est rejeté, jamais écrit vide.

    `detail` nomme le jpath fautif, parce que c'est le paramétrage ou le template qu'il
    faut corriger, et que l'appelant n'a aucun moyen de le deviner depuis « clé absente ».
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class KeyRule:
    """Les jpath de clé d'un storage, COMPILÉS. Un chemin nul : jpath non singulier.

    Compilés une fois par DÉPÔT, et c'est tout l'objet de ce type. Mesuré le 06/11/2026
    sur la forme réelle d'un point relais : `path_keys("$.Code")` coûte **372,5 µs**, et
    il était appelé une fois par objet — soit 70 % du temps de préparation d'un item, et
    quatre fois le prix du template JSLT lui-même. La table, le modèle et la chaîne
    étaient déjà résolus une fois par dépôt ; la règle de clé avait été oubliée.
    """

    jpaths: tuple[str, ...]
    chemins: tuple[tuple[str | int, ...] | None, ...]


def key_rule(jpaths: tuple[str, ...]) -> KeyRule:
    """Compile les jpath de clé. À appeler UNE FOIS par dépôt, jamais par objet.

    Un jpath illisible n'est pas refusé ICI : il devient un chemin nul, et c'est à
    l'extraction que l'objet est rejeté, nommément. Refuser le dépôt entier aurait changé
    la forme du compte-rendu — aujourd'hui chaque objet porte son rejet.
    """
    return KeyRule(jpaths, tuple(path_keys(jpath) for jpath in jpaths))


def key_of(objet: Any, rule: KeyRule) -> str:
    """La clé de cet objet, composée des valeurs que les jpath désignent, dans l'ordre.

    **Toujours un tableau JSON, même pour un seul jpath**, et c'est un choix. Deux formes
    — le scalaire quand il y a un jpath, le tableau quand il y en a plusieurs — auraient
    fait changer la forme de TOUTES les clés déjà en base le jour où un storage gagne un
    second jpath de clé : l'écriture différentielle ne retrouverait plus aucune ligne, et
    recréerait la table entière en doublons sous des clés d'une autre forme. Une seule
    forme rend ce changement visible pour ce qu'il est — un changement d'identité — au lieu
    de le faire passer pour un import.

    Le tableau JSON plutôt qu'un séparateur : aucune valeur à échapper, et deux parties
    « a|b » et « a », « b » ne peuvent pas se confondre.
    """
    valeurs = [
        _value_at(objet, jpath, chemin)
        for jpath, chemin in zip(rule.jpaths, rule.chemins, strict=True)
    ]
    return json.dumps(valeurs, ensure_ascii=False, separators=(",", ":"))


def _value_at(objet: Any, jpath: str, keys: tuple[str | int, ...] | None) -> str:
    if keys is None:
        # Le jpath n'est pas un chemin singulier depuis la racine. Le module de
        # paramétrage le refuse à la saisie ; ici c'est un fichier de git qu'on n'a pas
        # écrit, et le refuser nommément vaut mieux que de l'ignorer.
        raise KeyNotExtractable(jpath)
    courant: Any = objet
    for cle in keys:
        courant = _descend(courant, cle)
        if courant is None:
            raise KeyNotExtractable(jpath)
    # Une clé composée d'un objet ou d'un tableau n'identifie rien de stable : son
    # rendu dépendrait de l'ordre des champs, donc de la source. Un booléen non plus :
    # deux valeurs ne font pas une identité.
    if isinstance(courant, (dict, list, bool)):
        raise KeyNotExtractable(jpath)
    # **La clé est TEXTUELLE, et c'est une décision** : 42 et "42" désignent le même
    # objet. Une source qui corrige le type JSON de son identifiant — de nombre vers
    # chaîne, ce qui arrive au premier changement de sérialiseur chez un partenaire —
    # dédoublerait sinon tout le référentiel d'un coup, chaque objet existant devenant
    # orphelin sous une clé d'une autre forme. Et aucune date ne le dirait : les anciens
    # seraient simplement « plus vus », donc sortis par le balayage des semaines plus tard.
    return courant if isinstance(courant, str) else json.dumps(courant)


def _descend(courant: Any, cle: str | int) -> Any:
    if isinstance(cle, int):
        if not isinstance(courant, list) or not -len(courant) <= cle < len(courant):
            return None
        return courant[cle]
    if not isinstance(courant, dict):
        return None
    return courant.get(cle)
