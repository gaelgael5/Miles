"""Une FENÊTRE GLISSANTE sur le texte d'un document, et les quatre gestes qui s'y font.

**Pourquoi pas un parseur SAX, qui était le choix d'origine.** Un tokeniseur rend un jeton
à la fois à Python, et un point relais de 3,81 Ko en compte environ quatre cents : la
traversée de frontière coûte ~2,5 µs, et l'analyse JSON n'est qu'une fraction de ce
qu'elle paie. Mesuré le 07/11/2026, les deux passes d'un import sur un document réel de
195,1 Mo et 50 000 objets : `json_stream` plus construction récursive, **42,92 s**, soit
858 µs par item ; la même lecture sur une fenêtre, **5,20 s**, soit 104 µs — huit fois moins, et
les 50 000 items rendus sont identiques un à un. Le document n'est toujours pas en mémoire
— c'est la fenêtre qui borne, au lieu du tokeniseur —, et la promesse du critère 1 de la
story `0f14adbd` tient par construction.

`raw_decode` est la pièce qui rend la chose possible : il analyse UNE valeur à partir d'un
indice et rend la valeur **et** l'indice de fin, par le scanner C du stdlib. Un appel par
item au lieu d'un par jeton, sans dépendance.

**Les deux pièges de `raw_decode`, tous deux mesurés, tous deux gardés ici** : il accepte
un PRÉFIXE valide (voir `decode_value`), et il ne borne pas la profondeur (voir
`_too_deep`). Les ignorer rendrait des items FAUX en silence, ce qui est pire que lent.
"""

from __future__ import annotations

import json
from typing import Any

from environnement.ingestion.jsonflux import (
    DOCUMENT_INVALID,
    DOCUMENT_TOO_DEEP,
    MAX_DEPTH,
    DocumentUnreadable,
)

# Taille de la fenêtre. 128 Kio : mesurée indiscernable de 1 Mio en débit (45 contre
# 42 µs par item) et elle garde le pic d'allocation deux ordres de grandeur sous la
# taille d'un document, ce que le test du critère 1 vérifie en relatif.
WINDOW = 128 << 10

# Au-delà, une seule valeur ne tient plus dans aucune fenêtre raisonnable et le document
# est tenu pour invalide. Borne la croissance du tampon : sans elle, un document fait
# d'un unique objet de plusieurs gigaoctets ferait grandir la fenêtre jusqu'à la mémoire.
VALUE_MAX = 64 << 20

# `strict=False` : les CARACTÈRES DE CONTRÔLE sont admis dans une chaîne, alors que
# RFC 8259 les interdit non échappés. Écart DÉLIBÉRÉ, décidé par Gael le 08/11/2026 sur un
# export réel — `"City" : "Gloucester<TAB>GL4 3HX"`, `"LastName" : "Meißner (Geb.<TAB>…"` —
# où la tabulation brute arrêtait la lecture à la première occurrence : 17 800 comptes lus
# sur un document qui en portait bien plus, et tout ce qui suivait jamais vu.
#
# Admissible parce que le cas est NON AMBIGU : un caractère de contrôle dans une chaîne ne
# peut être que du contenu de cette chaîne, et il n'y a aucune autre lecture à en faire —
# contrairement à une virgule finale ou à un `NaN`, qui demanderaient d'inventer une
# interprétation. On ne devine donc rien, on cesse seulement de refuser.
#
# Ce qui reste refusé ne bouge pas : une chaîne jamais refermée bute toujours sur
# `VALUE_MAX`, un document tronqué reste tronqué, un octet qui n'est pas de l'UTF-8 reste
# un refus. Et la traversée de `jsonskip`, qui ne cherche que `\` et `"`, les tolérait déjà
# — ce point-ci était le seul à ne pas le faire.
_DECODE = json.JSONDecoder(strict=False).raw_decode
# Publiques : `jsonskip` traverse les mêmes délimiteurs que `decode_value` contrôle.
BLANKS = " \t\r\n"
AFTER_VALUE = ",}]"


class Window:
    """Le texte disponible autour du curseur, et rien d'autre.

    Les positions manipulées sont ABSOLUES dans le document : c'est ce qui permet de
    faire glisser le tampon sous les appelants sans qu'aucun d'eux tienne un indice
    devenu faux. `anchor` est le point que l'appelant doit pouvoir relire — le début de
    la valeur en cours — et rien avant lui n'est conservé.
    """

    def __init__(self, handle: Any, size: int = WINDOW) -> None:
        self._handle = handle
        self._size = size
        self._text = self._read()
        self.start = 0

    @property
    def text(self) -> str:
        return self._text

    @property
    def stop(self) -> int:
        """La position absolue juste après le dernier caractère disponible."""
        return self.start + len(self._text)

    def local(self, position: int) -> int:
        return position - self.start

    def grow(self, anchor: int) -> bool:
        """Jette ce qui précède `anchor`, lit une fenêtre de plus. Faux à la fin."""
        suite = self._read()
        if not suite:
            return False
        garde = self.local(anchor)
        if garde > 0:
            self._text = self._text[garde:]
            self.start = anchor
        if len(self._text) + len(suite) > VALUE_MAX:
            # Volontairement rangé sous « document invalide » et non sous un code neuf :
            # les codes de refus sont lus par l'historique des ingestions, et en ajouter
            # un ferait évoluer un contrat pour un cas que le déposant corrige de la
            # même façon — en déposant un document bien formé.
            raise DocumentUnreadable(DOCUMENT_INVALID, f"valeur de plus de {VALUE_MAX} octets")
        self._text += suite
        return True

    def ensure(self, position: int, anchor: int) -> bool:
        """Vrai si `position` est lisible ; lit la suite autant qu'il faut."""
        while position >= self.stop:
            if not self.grow(anchor):
                return False
        return True

    def _read(self) -> str:
        try:
            lu: str = self._handle.read(self._size)
        except UnicodeDecodeError as erreur:
            # Le document n'est pas de l'UTF-8. Refus explicite : sans lui, l'erreur
            # remonterait brute depuis le codec et ne dirait pas que c'est le DÉPÔT qui
            # est en cause.
            raise DocumentUnreadable(DOCUMENT_INVALID, str(erreur)[:200]) from None
        return lu


def skip_blanks(window: Window, position: int, anchor: int, also: str = "") -> int:
    """La première position qui ne porte ni blanc ni l'un des caractères de `also`."""
    while window.ensure(position, anchor) and window.text[window.local(position)] in (
        BLANKS + also
    ):
        position += 1
    return position


def char_at(window: Window, position: int, anchor: int) -> str:
    """Le caractère à cette position, ou la chaîne vide à la fin du document."""
    if not window.ensure(position, anchor):
        return ""
    return window.text[window.local(position)]


def decode_value(
    window: Window, position: int, anchor: int, follows: str = AFTER_VALUE
) -> tuple[Any, int]:
    """La valeur JSON qui commence à `position`, et la position juste après elle.

    **La garde de troncature est ici, et elle n'est pas optionnelle.** `raw_decode` rend
    une valeur VALIDE tirée d'un préfixe : `123456789` coupé par la fenêtre en `123`
    s'analyse sans lever quoi que ce soit, et l'item rendu serait faux SANS AUCUNE ERREUR
    (mesuré : une fenêtre de 18 octets rendait `1234` au lieu de `123456789`). On exige
    donc que la valeur soit suivie d'un délimiteur ; sinon on agrandit et on réanalyse.
    Un item est le plus souvent un objet, qui lui échoue franchement — mais le découpage
    est paramétrable et peut désigner un tableau de scalaires.
    """
    while True:
        try:
            valeur, local_stop = _DECODE(window.text, window.local(position))
        except RecursionError:
            raise DocumentUnreadable(DOCUMENT_TOO_DEEP, str(MAX_DEPTH)) from None
        except ValueError as erreur:
            if window.grow(anchor):
                continue
            raise DocumentUnreadable(DOCUMENT_INVALID, str(erreur)[:200]) from None
        stop = window.start + local_stop
        if stop >= window.stop and window.grow(anchor):
            # La valeur finit exactement au bord du tampon : elle est peut-être COUPÉE,
            # et `raw_decode` n'a aucun moyen de le dire — `123456789` tronqué en
            # `12345678` est un nombre valide. On agrandit et on réanalyse. C'est le seul
            # endroit où la correction se joue, et il coûte une réanalyse par fenêtre.
            continue
        apres = skip_blanks(window, stop, anchor)
        suivant = char_at(window, apres, anchor)
        if suivant == "":
            if window.grow(anchor):
                continue
            # Fin du document sans délimiteur : la valeur est peut-être AMPUTÉE, et c'est
            # le cas où `raw_decode` est dangereux — un `123456789` coupé en `123` est un
            # nombre valide. On refuse au lieu de rendre une valeur plausible et fausse.
            raise DocumentUnreadable(DOCUMENT_INVALID, "valeur non terminee")
        if suivant not in follows:
            raise DocumentUnreadable(DOCUMENT_INVALID, f"caractere inattendu : {suivant!r}")
        _check_depth(window, position, stop, valeur)
        return valeur, stop


def read_key(window: Window, position: int) -> tuple[str, int]:
    """Le nom de la propriété qui commence à `position`, et la position après son « : »."""
    if char_at(window, position, position) != '"':
        raise DocumentUnreadable(DOCUMENT_INVALID, "nom de propriete attendu")
    cle, stop = decode_value(window, position, position, follows=":")
    if not isinstance(cle, str):
        raise DocumentUnreadable(DOCUMENT_INVALID, "nom de propriete attendu")
    return cle, skip_blanks(window, stop, position) + 1


def _check_depth(window: Window, position: int, stop: int, valeur: Any) -> None:
    """Refuse une valeur trop imbriquée, au lieu de la subir.

    **Filtre bon marché d'abord, et c'est tout l'intérêt.** La profondeur d'une valeur est
    au plus son nombre de crochets ouvrants : deux `count` en C sur la tranche de texte
    déjà en tampon suffisent à l'écarter, et le parcours de l'objet n'a lieu que si ce
    majorant dépasse la borne — donc jamais sur un item normal. Mesuré à 7 µs par item ;
    la même garde posée en re-sérialisant l'objet rendu coûtait 80 µs.
    """
    tranche = window.text[window.local(position) : window.local(stop)]
    if tranche.count("{") + tranche.count("[") < MAX_DEPTH:
        return
    if _too_deep(valeur):
        raise DocumentUnreadable(DOCUMENT_TOO_DEEP, str(MAX_DEPTH))


def _too_deep(valeur: Any) -> bool:
    """Vrai si l'imbrication des conteneurs atteint `MAX_DEPTH`.

    Parcours ITÉRATIF, avec une pile explicite : la garde existe pour qu'un document
    fautif produise un refus rendu et non un débordement de pile, et la rendre par une
    récursion la remplacerait par le défaut qu'elle évite. L'analyseur C, lui, ne borne
    rien — mesuré : il a construit 2 000 niveaux sans broncher.
    """
    pile = [(valeur, 1)]
    while pile:
        noeud, niveau = pile.pop()
        if isinstance(noeud, dict):
            if niveau >= MAX_DEPTH:
                return True
            pile.extend((valeur, niveau + 1) for valeur in noeud.values())
        elif isinstance(noeud, list):
            if niveau >= MAX_DEPTH:
                return True
            pile.extend((valeur, niveau + 1) for valeur in noeud)
    return False
