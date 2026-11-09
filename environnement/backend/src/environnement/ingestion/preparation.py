"""Préparer UN item : le transformer, le confronter au modèle, en extraire la clé.

**Module PUR, et c'est ce qui le rend partageable.** Les trois décisions qui scellent le
sort d'un objet avant toute écriture sont ici, et les deux modes les prennent par le MÊME
code : les modes `element` et `tableau` enchaînent préparation et écriture dans l'appel, le
mode gros fichier prépare HORS transaction et n'écrit qu'après (story `0f14adbd`). Une
seconde copie de ces trois décisions aurait fini par rejeter d'un côté ce que l'autre
écrit, pour le même document.

**L'ordre des trois contrôles n'est pas indifférent.** La TRANSFORMATION d'abord, parce que
tout le reste porte sur son résultat. Puis le MODÈLE, parce qu'une propriété de clé absente
est le plus souvent une violation du modèle, et « modèle non respecté, à tel chemin » envoie
corriger le template là où « clé non extractible » laisse chercher. La CLÉ en dernier, sur
un objet dont on sait déjà qu'il a la forme attendue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from miles_socle.transform.chain import ChainFailedError, run_chain

from environnement.ingestion.conformance import ModelViolation, check_conformance
from environnement.ingestion.fingerprint import fingerprint
from environnement.ingestion.keys import KeyNotExtractable, KeyRule, key_of
from environnement.ingestion.outcome import (
    REJECT_KEY_MISSING,
    REJECT_MODEL,
    REJECT_TRANSFORM,
    REJECTED,
    ObjectOutcome,
)


@dataclass(frozen=True)
class PreparedObject:
    """Un item prêt à écrire, ou le rejet décidé avant qu'aucune écriture n'ait lieu.

    Les deux dans le même type, et non deux types : c'est une ligne de l'aire de
    préparation, et l'aire porte les deux — le rejet doit y figurer pour que le
    compte-rendu le nomme, et pour que le rang des items reste celui du document.
    """

    position: int
    key: str | None
    objet: Any | None
    empreinte: bytes | None
    reason: str | None = None
    detail: str | None = None

    @property
    def writable(self) -> bool:
        return self.reason is None

    def rejection(self) -> ObjectOutcome:
        """Le sort de cet item, pour le compte-rendu. À n'appeler que sur un rejet."""
        return ObjectOutcome(self.position, REJECTED, self.key, self.reason, self.detail)


def prepare_object(
    chain: Any, validator: Any, keys: KeyRule, position: int, source: Any, budget: int
) -> PreparedObject:
    """Transforme, confronte et identifie. Ne touche ni la base ni l'arbre git.

    **Rien n'est COMPILÉ ici** : la chaîne, le validateur du modèle et la règle de clé
    arrivent tout faits, résolus une fois par dépôt. C'était déjà vrai des deux premiers ;
    la règle de clé recompilait son jpath à chaque objet — 372,5 µs mesurés, soit 70 % du
    temps de préparation d'un item (06/11/2026).
    """
    try:
        trace = run_chain(chain, source, budget)
    except ChainFailedError as echec:
        # Le rang de l'étape ET le code de l'erreur du moteur : « transformation en
        # échec » sans eux n'envoie nulle part sur une chaîne de plusieurs étapes.
        detail = f"etape {echec.step}: {echec.cause.code}"
        return _refuse(position, REJECT_TRANSFORM, detail)
    # Le message après la dernière étape. Une chaîne sans étape rend la trace vide, et
    # l'objet source est alors le résultat — voir `file_load_chain`.
    objet = trace[-1] if trace else source
    try:
        check_conformance(objet, validator)
    except ModelViolation as ecart:
        # LA CLÉ EST GARDÉE SUR UN REJET DE MODÈLE, quand elle s'extrait (story
        # `82bc9dca`). Deux conséquences, et la seconde est la raison :
        #
        # - le compte-rendu nomme l'item par sa clé, ce que son propre contrat annonce
        #   déjà (« `key` est nulle quand elle n'a pas pu être extraite ») ;
        # - surtout, le MARQUAGE DES ABSENTS la lit dans l'aire de préparation pour ne pas
        #   marquer absent un item dont le document parlait. Sans elle, un item que le
        #   modèle refuse serait supprimé au bout du délai — c'est-à-dire exactement celui
        #   qu'il fallait aller corriger. L'objet, lui, reste nul : il n'y a rien à écrire.
        return _refuse(position, REJECT_MODEL, ecart.detail, _key_or_none(objet, keys))
    try:
        cle = key_of(objet, keys)
    except KeyNotExtractable as manque:
        return _refuse(position, REJECT_KEY_MISSING, manque.detail)
    return PreparedObject(position, cle, objet, fingerprint(objet))


def _key_or_none(objet: Any, keys: KeyRule) -> str | None:
    """La clé d'un objet déjà REFUSÉ. Nulle sans bruit : l'item est rejeté de toute façon,
    et une propriété de clé absente est le plus souvent la violation qu'on vient de dire."""
    try:
        return key_of(objet, keys)
    except KeyNotExtractable:
        return None


def _refuse(
    position: int, reason: str, detail: str | None, key: str | None = None
) -> PreparedObject:
    return PreparedObject(position, key, None, None, reason, detail)
