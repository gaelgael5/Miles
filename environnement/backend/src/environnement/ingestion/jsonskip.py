"""Traverser une valeur SANS la lire : la seconde porte de la fenêtre.

Deux usages, et deux seulement :

- la **descente** par le découpage (`jsonpath`), où une propriété qui précède le tableau
  visé doit être franchie sans être construite — rien ne garantit qu'elle soit petite ;
- la **mesure** d'une valeur de métadonnée (`stream`), dont on veut l'étendue avant de
  l'analyser, pour refuser un en-tête démesuré au lieu de le bâtir puis de le jeter.

Les deux diffèrent sur un point qui décide de la mémoire : la descente laisse la fenêtre
GLISSER derrière le curseur, la mesure RETIENT le début de la valeur parce que l'appelant
va la réanalyser. D'où `skip_value` et `measure_value`, et un seul mécanisme dessous.

**Traverser n'est pas moins cher qu'analyser, et c'est contre-intuitif.** Mesuré le
07/11/2026 sur 50 000 points relais de 3,81 Ko : un survol de cette forme coûte 241 µs par
item, les analyser entièrement en coûte 51 — une machine à états visite chaque guillemet du
document, là où l'analyseur C n'est appelé qu'une fois par item. D'où deux conséquences :
le tableau des items omis par la passe des métadonnées est DRAINÉ par l'analyseur et non
survolé (`stream._omit`), et ce module ne sert qu'aux deux usages ci-dessus, où ce qu'il
traverse n'a pas à être construit. C'est aussi ce qui a écarté le parallélisme de la
lecture : tout découpage en cœurs aurait un survol de ce genre pour préalable, donc
coûterait cinq fois ce qu'il prétend accélérer.
"""

from __future__ import annotations

import re

from environnement.ingestion.jsonflux import DOCUMENT_INVALID, DocumentUnreadable
from environnement.ingestion.jsonwindow import AFTER_VALUE, BLANKS, Window, char_at

# Les seuls caractères qui changent l'état d'une traversée : les bornes de chaîne,
# l'échappement, et les conteneurs. Tout le reste est franchi sans être visité.
_MARKERS = re.compile(r'["\\{}\[\]]')


def skip_value(window: Window, position: int) -> int:
    """La position juste après la valeur à `position`, SANS rien construire ni retenir.

    Sert là où une valeur doit être traversée et non lue : une propriété qui précède le
    tableau visé par le découpage, et dont rien ne garantit qu'elle soit petite. La
    construire pour l'atteindre annulerait la promesse du mode fichier sur un document
    dont le gros morceau n'est pas celui qu'on vient chercher. **La fenêtre glisse derrière
    le curseur** : traverser huit mégaoctets ne coûte pas huit mégaoctets.
    """
    fin = _skip(window, position, keep=False, limit=0)
    if fin < 0:  # pragma: no cover - sans limite, `_skip` ne rend jamais -1
        raise DocumentUnreadable(DOCUMENT_INVALID, "valeur demesuree")
    return fin


def measure_value(window: Window, position: int, limit: int) -> int:
    """L'étendue de la valeur à `position`, son DÉBUT restant lisible, ou -1 au-delà
    de `limit`.

    Deux différences avec `skip_value`, et les deux sont la raison d'être de cette
    seconde porte : la fenêtre ne glisse PAS — l'appelant va réanalyser la valeur depuis
    son début —, et la traversée s'arrête dès que `limit` est dépassée. C'est ce qui rend
    la borne de mémoire : sans arrêt pendant la traversée, le tampon aurait déjà grandi
    jusqu'à la valeur entière quand l'appelant la jugerait démesurée.

    Rend -1 plutôt que de lever : c'est l'appelant qui sait sous quel code refuser.
    """
    return _skip(window, position, keep=True, limit=limit)


def _skip(window: Window, position: int, *, keep: bool, limit: int) -> int:
    debut = position
    premier = char_at(window, position, position)
    if premier == "":
        raise DocumentUnreadable(DOCUMENT_INVALID, "document tronque")
    if premier == '"':
        return _skip_string(window, position + 1, debut, keep=keep, limit=limit)
    if premier not in "{[":
        return _skip_scalar(window, position, debut, keep=keep, limit=limit)
    return _skip_container(window, position, debut, keep=keep, limit=limit)


def _anchor(debut: int, position: int, keep: bool) -> int:
    """Le point que la fenêtre doit conserver : le début de la valeur, ou rien."""
    return debut if keep else position


def _over(window: Window, debut: int, position: int, limit: int) -> bool:
    """Vrai quand la valeur dépasse `limit`, en comptant ce que le tampon RETIENT.

    Compter la seule position ne suffit pas : une plage sans marqueur fait grandir le
    tampon sans faire avancer le curseur, et le dépassement passerait inaperçu jusqu'à
    la borne dure. En prenant `window.stop`, la traversée s'arrête après `limit` plus une
    fenêtre, ce qui est la borne qu'on cherche.
    """
    return bool(limit) and max(position, window.stop) - debut > limit


def _skip_scalar(window: Window, position: int, debut: int, *, keep: bool, limit: int) -> int:
    """Un nombre ou un littéral : court par nature, donc parcouru caractère par
    caractère."""
    while True:
        if _over(window, debut, position, limit):
            return -1
        caractere = char_at(window, position, _anchor(debut, position, keep))
        if caractere == "" or caractere in AFTER_VALUE or caractere in BLANKS:
            return position
        position += 1


def _skip_string(window: Window, position: int, debut: int, *, keep: bool, limit: int) -> int:
    """La position juste après le guillemet fermant, échappements compris.

    Par la même recherche de marqueurs que les conteneurs, et non caractère par caractère :
    une propriété peut porter des mégaoctets de texte, et la parcourir en Python coûterait
    une traversée de frontière par octet — exactement ce que cette réécriture supprime.
    """
    while True:
        if _over(window, debut, position, limit):
            return -1
        marque = _MARKERS.search(window.text, window.local(position))
        if marque is None:
            # Rien d'intéressant jusqu'au bord du tampon : on avance DESSUS avant
            # d'agrandir. Sans cela, une propriété de huit mégaoctets sans guillemet
            # intérieur ferait grandir la fenêtre de huit mégaoctets — la traversée
            # cesserait d'être bornée, ce qui est tout ce qu'on lui demande.
            position = window.stop
            if window.grow(_anchor(debut, position, keep)):
                continue
            raise DocumentUnreadable(DOCUMENT_INVALID, "chaine non terminee")
        position = window.start + marque.start() + 1
        if marque.group() == "\\":
            position += 1
        elif marque.group() == '"':
            return -1 if _over(window, debut, position, limit) else position


def _skip_container(window: Window, position: int, debut: int, *, keep: bool, limit: int) -> int:
    """La position juste après le conteneur, par machine à états sur les seuls marqueurs.

    L'état — profondeur et « dans une chaîne » — est tenu hors de la boucle de recherche,
    parce que le tampon glisse sous elle : chaque agrandissement redémarre la recherche
    là où elle en était, sans perdre ce qui a été établi.
    """
    profondeur = 0
    dans_chaine = False
    while True:
        if _over(window, debut, position, limit):
            return -1
        marque = _MARKERS.search(window.text, window.local(position))
        if marque is None:
            position = window.stop  # voir `_skip_string` : on avance avant d'agrandir
            if window.grow(_anchor(debut, position, keep)):
                continue
            raise DocumentUnreadable(DOCUMENT_INVALID, "conteneur non ferme")
        position = window.start + marque.start() + 1
        octet = marque.group()
        if dans_chaine:
            if octet == "\\":
                position += 1
            elif octet == '"':
                dans_chaine = False
            continue
        if octet == '"':
            dans_chaine = True
        elif octet in "{[":
            profondeur += 1
        else:
            profondeur -= 1
            if profondeur == 0:
                return -1 if _over(window, debut, position, limit) else position
