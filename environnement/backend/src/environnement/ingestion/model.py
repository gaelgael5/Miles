"""Ce qu'un dépôt d'ingestion EST, et les raisons pour lesquelles on le refuse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from miles_socle.parametrage.sources import Entry

from environnement.ingestion.outcome import Report

ELEMENT = "element"
BATCH = "tableau"
FILE = "fichier"
MODES = (ELEMENT, BATCH, FILE)
# Les modes que CE ticket sert. `fichier` est déclarable par le paramétrage et refusé
# ici, nommément : son dépôt sur disque et son traitement en flux sont la story 0f14adbd.
# Refusé plutôt qu'accepté sans effet — un acquittement sur un mode non branché
# laisserait croire qu'un lot a été pris en charge.
SERVED_MODES = (ELEMENT, BATCH)

RECEIVED_EVENT = "environment.ingestion_received"
EVENT_TYPES = frozenset({RECEIVED_EVENT})
INGESTION_OBJECT_KIND = "ingestion"
STATE_RECEIVED = "recu"

CONTENT_TYPE = "application/json"
# Les types admis pour un dépôt de FICHIER. Le flux d'octets en plus du JSON : un outil qui
# pousse un fichier n'annonce souvent rien de mieux, et le refuser l'obligerait à mentir sur
# son type pour déposer le même document.
OCTET_STREAM = "application/octet-stream"
FILE_CONTENT_TYPES = frozenset({CONTENT_TYPE, OCTET_STREAM})
# Taille maximale du corps reçu. Le mode `tableau` est plafonné à 200 objets ; cette borne
# est la seconde, en OCTETS, et elle existe parce que le compte d'objets ne se connaît
# qu'après avoir tout lu. Sans elle, un corps de plusieurs gigaoctets serait chargé en
# mémoire avant d'être refusé pour son nombre d'items.
MAX_BODY_BYTES = 8 * 1024 * 1024

# Refus, et chacun dit à l'appelant ce qu'il doit corriger.
REFUSAL_MODE_INCONNU = "mode_inconnu"
REFUSAL_MODE_NON_DECLARE = "mode_non_declare"
REFUSAL_MODE_AMBIGU = "mode_ambigu"
REFUSAL_MODE_NON_SERVI = "mode_non_servi"
REFUSAL_SOURCE_INCONNUE = "source_inconnue"
REFUSAL_SOURCE_ILLISIBLE = "source_illisible"
REFUSAL_TYPE_DE_CONTENU = "type_de_contenu_inattendu"
REFUSAL_CORPS_VIDE = "corps_vide"
REFUSAL_CORPS_TROP_GRAND = "corps_trop_grand"
REFUSAL_JSON_INVALIDE = "json_invalide"
REFUSAL_OBJET_ATTENDU = "objet_attendu"
REFUSAL_TABLEAU_ATTENDU = "tableau_attendu"
REFUSAL_LOT_TROP_GRAND = "lot_trop_grand"
REFUSAL_AUCUNE_VERSION = "aucune_version_servie"
# La version servie ne porte pas ce que l'entrée désigne : son storage, le modèle de ce
# storage, ou la chaîne qui y mène. Refus de DÉPÔT et non rejet d'objet : aucun objet de
# ce lot ne pourrait aboutir, et `detail` nomme lequel des trois manque.
REFUSAL_CIBLE_NON_SERVIE = "cible_non_servie"


class IngestionRefusal(Exception):
    """Dépôt refusé avant toute écriture. `code` est stable, `detail` aide à corriger."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code if detail is None else f"{code}:{detail}")
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Target:
    """Ce qu'une adresse d'ingestion désigne, résolu contre la version servie."""

    source: str
    mode: str
    entry: Entry
    # Le storage où les objets atterrissent. Porté par la SOURCE et non par l'entrée :
    # plusieurs entrées d'une même source alimentent le même storage par des modèles
    # d'entrée différents. Recopié ici pour que le traitement n'ait pas à relire la
    # déclaration — il l'a déjà résolue pour en tirer l'entrée.
    storage: str


@dataclass(frozen=True)
class Acknowledgement:
    """L'accusé rendu à l'appelant : ce qui est reçu, et ce que le traitement en a fait.

    Il ne disait que « reçu » jusqu'au 03/11/2026 : la transformation et l'écriture
    différentielle étaient le ticket suivant. Depuis la story `d680e811`, les modes
    `element` et `tableau` traitent le lot dans l'appel et rendent son compte-rendu —
    décision de Gael du 02/11/2026, « un array qui décris pour chaque clef fonctionnel le
    retour ».
    """

    id: str
    source: str
    mode: str
    object_count: int
    received_at: datetime
    state: str
    # Vrai quand la clé d'idempotence de l'appelant a retrouvé un dépôt déjà pris : la
    # même ingestion est rendue, et rien n'a été persisté une seconde fois.
    replayed: bool
    # Le sort de chaque objet du lot. Nul tant que le lot n'est pas traité — c'est l'état
    # qu'un service interrompu laisse derrière lui, et celui qui fait REPRENDRE le
    # traitement au rejeu plutôt que rendre un compte-rendu vide (critère 14).
    report: Report | None = None
