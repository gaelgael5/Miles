"""Éditer l'artefact d'un périmètre SANS perdre ce que le portail n'écrit pas.

La grammaire d'un `FRAGMENT` admet **cinq** sortes de déclarations : `DEFINE EVENT`,
`RULE`, `ACTION`, `ARTIFACT` et `CONST`. Le portail n'en écrit qu'une. Jusqu'au
17/11/2026 il réécrivait pourtant le fichier ENTIER depuis sa seule liste de types
d'event : le premier geste sur un type effaçait sans un mot toute règle, action, artefact,
constante et le `DESCRIPTION` du fichier (bug `ff8779c6`). Le geste réussissait, la version
s'enregistrait, et la perte ne se voyait qu'au chargement par le moteur — ou jamais.

Ce module fait l'inverse : il ÉDITE le texte existant. Chaque déclaration est située par
le PARSEUR DU MOTEUR, qui donne son étendue au caractère près (`ctx.start.start`, et le
`;` qui la termine) ; seules les étendues des types d'event sont remplacées, retirées ou
suivies d'une ligne nouvelle. Tout le reste — en-tête, `DESCRIPTION`, déclarations des
quatre autres sortes, lignes vides — traverse le geste à l'octet près, parce qu'il n'est
jamais réécrit.

Aucune expression régulière ne lit du DSL ici, et c'est un interdit du ticket : le
découpage vient de l'arbre d'analyse du moteur, et les positions avec lui. Une sorte de
déclaration que le moteur connaîtrait et que ce module n'énumère pas est CONSERVÉE pour
la même raison — elle est lue, pas devinée.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from urban_workflow.dsl.generated.WorkflowParser import WorkflowParser
from urban_workflow.dsl.parser import WorkflowScriptParser

from miles.workflowevents.dsl import (
    DslProblem,
    EventType,
    FragmentError,
    render,
    render_event,
)

EVENT = "event"
RULE = "rule"
ACTION = "action"
ARTIFACT = "artifact"
CONST = "const"
# Une sorte que le moteur saurait lire et que Miles ne nomme pas : elle se conserve comme
# les autres. C'est la seule différence que ce module fait entre « connue » et « la nôtre ».
OTHER = "other"

# Les sortes, par la CLASSE du contexte d'analyse plutôt que par son nom en chaîne : une
# classe renommée dans le paquet casse l'import, un nom en chaîne ferait silencieusement
# tomber la sorte dans `OTHER` — donc conserver un type d'event au lieu de le réécrire.
_KINDS = {
    WorkflowParser.Event_declaration_statementContext: EVENT,
    WorkflowParser.Rule_declaration_statementContext: RULE,
    WorkflowParser.Action_declaration_statementContext: ACTION,
    WorkflowParser.Artifact_declaration_statementContext: ARTIFACT,
    WorkflowParser.Constant_declarationContext: CONST,
}


@dataclass(frozen=True)
class Declaration:
    """Une déclaration de l'artefact, située comme le moteur la situe."""

    kind: str
    # Le nom déclaré, ou "" quand la sorte n'en expose pas un à cette place.
    name: str
    # Étendue dans le texte : `start` est le `D` de `DEFINE`, `end` est APRÈS le `;`.
    start: int
    end: int


def declarations(text: str) -> tuple[Declaration, ...]:
    """Les déclarations de l'artefact, dans l'ordre du fichier ; lève `FragmentError`.

    Le même refus que `dsl.parse` : un artefact qui ne se relit pas n'est pas édité, et
    surtout pas réécrit depuis ce qu'on a cru y lire.
    """
    script = WorkflowScriptParser.parse_string(text, "")
    if script.errors:
        raise FragmentError([DslProblem(e.line, e.column, e.message) for e in script.errors])
    if not script.is_fragment:
        raise FragmentError([DslProblem(1, 0, "un artefact de périmètre est un FRAGMENT")])
    found = []
    pending: Declaration | None = None
    fragment = script.tree.getChild(0)
    for index in range(fragment.getChildCount()):
        child = fragment.getChild(index)
        if isinstance(child, WorkflowParser.Define_referenciel_statementContext):
            # L'étendue s'arrête avant le `;`, qui est un frère de ce nœud : on la ferme
            # au point-virgule suivant, pris de l'arbre et non cherché dans le texte.
            pending = Declaration(*_kind_and_name(child), child.start.start, child.stop.stop + 1)
            continue
        # Le `;` qui ferme la déclaration : un nœud TERMINAL, reconnu à son jeton plutôt
        # qu'importé d'`antlr4.tree` — le paquet du runtime ANTLR n'a pas de stubs, et
        # `symbol` suffit à distinguer un terminal d'un contexte.
        symbol = getattr(child, "symbol", None)
        if pending is not None and symbol is not None and symbol.text == ";":
            found.append(Declaration(pending.kind, pending.name, pending.start, symbol.stop + 1))
            pending = None
    return tuple(found)


def rewrite(current: str | None, scope: str, types: Sequence[EventType]) -> str:
    """L'artefact après le geste. Chaîne vide : il ne reste RIEN à déclarer.

    Pas de fichier, ou un fichier sans déclaration : on l'écrit en entier, comme avant —
    il n'y a rien à conserver. Sinon, on ÉDITE : chaque type d'event déjà déclaré est
    remplacé **à sa place** (ce qui garde l'ordre stable d'un geste à l'autre), ceux qui
    ont disparu voient leur étendue retirée, et les nouveaux s'ajoutent à la fin.

    À la fin, le résultat est RELU : un découpage qui aurait produit du DSL invalide lève
    plutôt que d'entrer dans le dépôt. C'est aussi ce qui dit s'il reste une déclaration —
    un `FRAGMENT` vide est une erreur de syntaxe pour le moteur, donc le fichier se retire.
    """
    if current is None or not current.strip():
        return render(scope, types)
    found = declarations(current)
    wanted = {declared.name: declared for declared in types}
    text = current
    kept = set()
    # De la FIN vers le début : chaque découpe décale ce qui la suit, et remonter à
    # l'envers garde les étendues des déclarations non encore traitées valides.
    for declared in sorted(found, key=lambda d: d.start, reverse=True):
        if declared.kind != EVENT:
            continue
        if declared.name in wanted:
            kept.add(declared.name)
            text = (
                text[: declared.start] + render_event(wanted[declared.name]) + text[declared.end :]
            )
        else:
            text = text[: declared.start] + text[_after(text, declared.end) :]
    added = [render_event(t) for t in types if t.name not in kept]
    if added:
        text = text if text.endswith("\n") else text + "\n"
        text += "".join(f"{line}\n" for line in added)
    # « Reste-t-il quelque chose ? » se répond AVANT de relire, et non après : un
    # `FRAGMENT` sans déclaration est une erreur de syntaxe, donc un artefact devenu vide
    # ne se relit pas — demander au moteur ferait lever là où il faut rendre la chaîne
    # vide, c'est-à-dire retirer le fichier.
    if not types and not [d for d in found if d.kind != EVENT]:
        return ""
    # Relu par le moteur : ce qui sort d'ici se charge, ou rien ne s'écrit. Un découpage
    # qui aurait produit du DSL invalide lève plutôt que d'entrer dans le dépôt.
    declarations(text)
    return text


def _after(text: str, end: int) -> int:
    """La fin d'une étendue retirée, saut de ligne compris.

    Sans lui, supprimer une déclaration laisserait une ligne vide de plus à chaque geste.
    C'est de la mise en forme du découpage, pas de la lecture de DSL : on ne consomme que
    des blancs, et UN seul saut de ligne.
    """
    index = end
    while index < len(text) and text[index] in " \t":
        index += 1
    if text[index : index + 2] == "\r\n":
        return index + 2
    if index < len(text) and text[index] == "\n":
        return index + 1
    return end


def _kind_and_name(
    statement: WorkflowParser.Define_referenciel_statementContext,
) -> tuple[str, str]:
    """La sorte d'une déclaration et le nom qu'elle déclare, lus de l'arbre du moteur."""
    for index in range(statement.getChildCount()):
        child = statement.getChild(index)
        kind = _KINDS.get(type(child))
        if kind is not None:
            return kind, _declared_name(child)
    return OTHER, ""


def _declared_name(declaration: object) -> str:
    """Le premier `key` d'une déclaration : c'est là que toutes les sortes nomment."""
    node = declaration
    for index in range(node.getChildCount()):  # type: ignore[attr-defined]
        child = node.getChild(index)  # type: ignore[attr-defined]
        if isinstance(child, WorkflowParser.KeyContext):
            return str(child.getText())
    return ""
