"""Ce qu'un dépôt d'ingestion EST, et les raisons pour lesquelles on le refuse."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from miles_socle.events.catalog import EventShape, closed_block
from miles_socle.parametrage.sources import Entry

from environnement.ingestion.outcome import Report

ELEMENT = "element"
BATCH = "tableau"
FILE = "fichier"
MODES = (ELEMENT, BATCH, FILE)
# Les modes que CETTE stack sert. Les trois depuis le 04/11/2026 : `fichier` était
# déclarable par le paramétrage et refusé ici en attendant son dépôt sur disque et son
# traitement en flux (story 0f14adbd), qui sont faits.
#
# LA DISTINCTION RESTE, et `mode_non_servi` est donc aujourd'hui inatteignable — c'est
# dit pour que personne ne cherche le cas. Elle reste parce qu'elle n'est pas un vestige
# de cette story : c'est le mécanisme par lequel un mode que le paramétrage sait déclarer
# peut précéder son service ici, et le prochain mode ajouté en aura besoin le jour où il
# sera écrit dans la grammaire des sources avant d'être branché. Un acquittement sur un
# mode non branché laisserait croire qu'un lot a été pris en charge.
SERVED_MODES = (ELEMENT, BATCH, FILE)

RECEIVED_EVENT = "environment.ingestion_received"
_COMMUNS: dict[str, object] = {
    "source": {"type": "string", "minLength": 1},
    # DÉRIVÉ de `MODES` : un mode ajouté là-bas entre ici tout seul.
    "mode": {"type": "string", "enum": list(MODES)},
    "entry_model": {"type": "string", "minLength": 1},
    # Le LIBELLÉ de la clé, jamais la clé ni son empreinte : l'auteur de l'event est déjà
    # son identifiant, et le libellé est ce qu'un humain reconnaît dans le journal.
    "key_label": {"type": "string"},
}
_RECU = closed_block(
    {
        **_COMMUNS,
        "storage": {"type": "string", "minLength": 1},
        "size_bytes": {"type": "integer", "minimum": 0},
        "object_count": {"type": "integer", "minimum": 0},
    },
    tuple(_COMMUNS),
)
# Deux producteurs pour un seul type, mesurés le 12/11/2026 : le dépôt de FICHIER porte
# son storage et sa taille en octets, les modes élément et tableau portent leur nombre
# d'objets — qui ne se connaît qu'après avoir tout lu. Le seul type de Miles dont le bloc
# dépend d'une de ses propriétés, et donc le seul à porter un `if/then`. Les rendre tous
# facultatifs laisserait passer un dépôt de fichier sans sa taille, qui est ce qu'on lit
# en premier quand une ingestion est lente.
_RECU["allOf"] = [
    {
        "if": {"properties": {"mode": {"const": FILE}}, "required": ["mode"]},
        "then": {"required": ["size_bytes", "storage"]},
        "else": {"required": ["object_count"]},
    }
]
EVENT_SHAPES = (EventShape(RECEIVED_EVENT, "Dépôt d'ingestion reçu", _RECU),)
EVENT_TYPES = frozenset(forme.name for forme in EVENT_SHAPES)
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


def declared_length(header: str | None) -> int | None:
    """La taille que l'appelant ANNONCE, si elle est annoncée et lisible.

    Une valeur illisible est traitée comme une absence plutôt que refusée : les gardes sur
    la taille RÉELLE restent, et refuser sur un en-tête mal formé aurait fermé la porte à
    un client correct derrière un relais bavard. Ce qui est refusé pour de bon, c'est le
    dépôt qui dépasse les bornes — mesuré, pas annoncé.

    Ici depuis le 07/11/2026, et non plus privé du point d'entrée fichier : l'essai depuis
    l'écran s'en sert aussi, pour refuser un corps trop grand AVANT de le lire. Deux
    lectures de cet en-tête auraient divergé sur ce point précis — ce qu'on fait d'une
    valeur illisible —, et l'une des deux aurait fini par refuser ce que l'autre accepte.
    """
    if header is None:
        return None
    try:
        return int(header)
    except ValueError:
        return None


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
