"""L'artefact qui déclare les types d'event d'un périmètre : un FRAGMENT du DSL du moteur.

Depuis le 13/11/2026, **un type d'event n'est plus un fichier** : c'est une DÉCLARATION.
Le schéma de son payload est un modèle de données ordinaire, rangé avec les autres sous
`models/` ; ce qui en fait un type d'event, c'est qu'un `DEFINE EVENT … AS @modele` le
nomme. Conséquence assumée : un storage ou une source peut désormais désigner ce modèle,
ce que la liste séparée interdisait.

Le support de ces déclarations est un `FRAGMENT` du DSL d'`urban-workflow`, et non un
YAML maison : c'est le moteur qui le lira, et un format intermédiaire aurait voulu dire un
traducteur à tenir à jour dans les deux sens. Un script de workflow l'`INCLUDE` par son
nom de FICHIER — ce que `urban_workflow.dsl.loader.load_directory` indexe.

Module PUR : aucun accès au dépôt. Il n'écrit et ne lit que du texte, et c'est le PARSEUR
DU MOTEUR qui le relit — jamais une expression régulière maison. C'est ce qui garantit
qu'on lit exactement ce que le moteur lira, et ce qui fait que ses règles de nommage sont
MESURÉES ici plutôt que supposées.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from urban_workflow.dsl.generated.WorkflowLexer import WorkflowLexer
from urban_workflow.dsl.parser import WorkflowScriptParser
from urban_workflow.dsl.visitor import WorkflowConfigVisitor
from urban_workflow.exceptions import WorkflowError

from miles.datamodels.layout import SHARED

# Un identifiant du DSL (`REGULAR_ID`), mesuré le 14/11/2026 sur urban-workflow 0.2.1 :
# une lettre, puis lettres, chiffres et soulignés. Un souligné en tête est une erreur de
# LEXER (« token recognition error at: '_' »), un chiffre en tête une erreur de parseur,
# et tout caractère accentué une erreur de lexer — d'où la plage ASCII stricte.
IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# Les mots que le DSL se réserve, LUS du lexer installé plutôt que recopiés : la liste
# a 48 entrées aujourd'hui, et une montée du moteur en ajouterait sans que personne ne
# pense à venir ici. Même geste que la racine des events, lue du moteur elle aussi.
#
# Tous sont en MAJUSCULES et le lexer est sensible à la casse : `UNIQUE (State)` passe,
# `UNIQUE (EVENT)` non (« mismatched input 'EVENT' expecting REGULAR_ID »). Un nom
# d'event de Miles est en minuscules, donc hors d'atteinte ; une propriété de payload,
# elle, vient du schéma et peut tomber dessus.
RESERVED = frozenset(mot for nom in WorkflowLexer.literalNames if (mot := nom.strip("'")).isalpha())

# Le fichier d'un périmètre, nommé D'APRÈS lui. Pas un nom commun (`referentiel.wf`)
# répété dans chaque dossier : `load_directory` indexe les fragments par chemin complet
# ET par nom de fichier seul, donc deux périmètres homonymes s'éclipseraient dans l'index
# d'`INCLUDE`, le dernier chargé gagnant — en silence.
SUFFIX = ".wf"


@dataclass(frozen=True)
class EventType:
    """Un type d'event déclaré : son nom DSL, son libellé, le modèle de son payload."""

    name: str
    label: str
    # (portée, nom) du modèle désigné par `AS @…`.
    model: tuple[str, str]
    # Clés de l'anti-doublon (`UNIQUE (…)`), DANS L'ORDRE DE SAISIE : le moteur en dérive
    # un hash par concaténation (`compute_dedup_hash`), donc deux ordres donnent deux
    # hashs. L'ordre est une donnée, pas une présentation.
    unique: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class DslProblem:
    """Un manquement de l'artefact, positionné comme le moteur le positionne."""

    line: int
    column: int
    message: str


class FragmentError(ValueError):
    """L'artefact ne se relit pas : TOUS les manquements, pas seulement le premier."""

    def __init__(self, problems: Sequence[DslProblem]) -> None:
        super().__init__(f"{len(problems)} manquement(s) dans l'artefact de déclaration")
        self.problems = tuple(problems)


def fragment_path(scope: str) -> str:
    """Où vit l'artefact d'un périmètre : à la racine du périmètre, à côté de `models/`.

    Dans le périmètre et non dans une rubrique : il ne décrit pas un objet du dossier, il
    déclare ce que le périmètre expose au moteur. Une rubrique de plus aurait fait croire
    qu'il peut y en avoir plusieurs, alors qu'il y en a exactement zéro ou un.
    """
    if scope == SHARED:
        return f"shared/shared{SUFFIX}"
    return f"domains/{scope}/{scope}{SUFFIX}"


def scope_of(path: str) -> str | None:
    """Le périmètre dont un chemin est l'artefact, ou None."""
    for candidate in _candidates(path):
        if fragment_path(candidate) == path:
            return candidate
    return None


def _candidates(path: str) -> list[str]:
    parts = path.split("/")
    if parts[:1] == ["shared"]:
        return [SHARED]
    if len(parts) == 3 and parts[0] == "domains":
        return [parts[1]]
    return []


def model_ref(scope: str, name: str) -> str:
    """Comment un `AS @…` désigne un modèle : le chemin, sans la rubrique, en pointé.

    `shared.colis` et `domains.livraison.colis` — mesuré le 14/11/2026 : le moteur rend
    la référence telle quelle dans `DeclaredEventConfig.schema_ref`, et c'est sous ce nom
    qu'un `SchemaRegistry` enregistrera le schéma. La portée y est OBLIGATOIRE, parce que
    le registre du moteur est PLAT : `shared/models/colis.yaml` et
    `domains/livraison/models/colis.yaml` s'y écraseraient sous le nom `colis`.

    Reste au produit, comme les chemins l'étaient avant lui : personne ne lit encore ces
    références hors du portail. Elles monteront au socle le jour où un module
    d'environnement montera son `SchemaRegistry` — et il faudra alors que les deux côtés
    en dérivent le même nom, au caractère près.
    """
    if scope == SHARED:
        return f"shared.{name}"
    return f"domains.{scope}.{name}"


def ref_target(ref: str) -> tuple[str, str] | None:
    """(portée, nom) du modèle qu'une référence désigne ; None si elle n'en désigne pas."""
    parts = ref.split(".")
    if len(parts) == 2 and parts[0] == SHARED:
        return SHARED, parts[1]
    if len(parts) == 3 and parts[0] == "domains":
        return parts[1], parts[2]
    return None


def writable(text: str) -> bool:
    """Le DSL sait-il écrire cet identifiant ?

    Sert à REFUSER À LA SAISIE ce que le moteur refuserait au chargement : un nom de
    domaine ou de modèle porte le tiret (`^[a-z0-9][a-z0-9_-]{0,62}$`), le DSL non —
    « mismatched input '-' expecting ';' ». Mieux vaut le dire au moment du geste que
    livrer un artefact qu'aucun moteur ne pourra lire.
    """
    return bool(IDENTIFIER_RE.match(text)) and text not in RESERVED


def render(scope: str, types: Sequence[EventType]) -> str:
    """L'artefact d'un périmètre, en texte. Aucun type : chaîne vide, et pas de fichier.

    Un `FRAGMENT` sans aucune déclaration est une ERREUR DE SYNTAXE pour le moteur
    (« mismatched input '<EOF>' expecting 'DEFINE' », mesuré le 14/11/2026) : la grammaire
    en exige au moins une. Écrire un artefact vide reviendrait donc à poser dans le dépôt
    un fichier qui fait échouer le chargement de tout le répertoire.

    Et l'en-tête ne porte PAS de `DESCRIPTION`, bien que la grammaire l'accepte :
    `visitScript_fragment` l'affecte à `_workflow.label`, le visiteur étant partagé avec
    le script qui l'`INCLUDE`. Le libellé de notre périmètre deviendrait donc celui de
    tout workflow dont le script n'a pas son propre `DESCRIPTION`.
    """
    if not types:
        return ""
    # Le NAME est ignoré par le visiteur du moteur (mesuré : `visitScript_fragment` ne lit
    # jamais `ctx.key()`) ; il est là pour qui ouvre le fichier. D'où le refus, en amont,
    # d'un périmètre que le DSL ne sait pas écrire : on n'invente pas un nom de
    # remplacement, qui ne désignerait plus rien de reconnaissable.
    lines = [f"FRAGMENT NAME {SHARED if scope == SHARED else scope}", ""]
    for declared in types:
        head = f"DEFINE EVENT {declared.name} {_quoted(declared.label)}"
        head += f" AS @{model_ref(*declared.model)}"
        if declared.unique:
            head += f" UNIQUE ({', '.join(declared.unique)})"
        lines.append(f"{head};")
    return "\n".join(lines) + "\n"


def _quoted(label: str) -> str:
    """Un libellé entre quotes simples ; `''` est l'échappement d'une apostrophe.

    Un libellé VIDE n'est pas écrivable — `''` est une erreur de lexer, mesurée — donc un
    type d'event a toujours un libellé, et c'est tenu à la saisie.
    """
    return "'" + label.replace("'", "''") + "'"


def parse(text: str) -> list[EventType]:
    """Relit un artefact avec le PARSEUR DU MOTEUR ; lève FragmentError.

    Rend les types dans l'ordre du fichier, et les clés d'unicité dans l'ordre écrit.
    """
    script = WorkflowScriptParser.parse_string(text, "")
    if script.errors:
        raise FragmentError([DslProblem(e.line, e.column, e.message) for e in script.errors])
    if not script.is_fragment:
        # Un script complet déclare un workflow, pas un référentiel de périmètre. Le
        # laisser passer ferait charger ses états et ses transitions depuis un fichier que
        # l'écran des types d'event présente comme une simple liste.
        raise FragmentError([DslProblem(1, 0, "un artefact de périmètre est un FRAGMENT")])
    try:
        # `visitScript` RETOURNE la configuration : pas de détour par l'état interne du
        # visiteur. Il ne `build()` que les scripts complets, donc rien d'autre que nos
        # déclarations n'est validé ici.
        config = script.visit(WorkflowConfigVisitor())
    except WorkflowError as exc:
        # Les doublons (nom d'event, clé d'unicité) ne sont PAS des erreurs de syntaxe :
        # le moteur les lève pendant la VISITE, positionnées dans le message. Sans ce
        # `except`, un artefact rendu par un autre outil ferait remonter une exception du
        # moteur jusqu'à la route.
        raise FragmentError([DslProblem(0, 0, str(exc))]) from exc
    found = []
    for declared in config.declared_events.values():
        target = ref_target(declared.schema_ref)
        if target is None:
            raise FragmentError(
                [DslProblem(0, 0, f"référence de modèle illisible : {declared.schema_ref!r}")]
            )
        found.append(EventType(declared.name, declared.label, target, tuple(declared.dedup_keys)))
    return found
