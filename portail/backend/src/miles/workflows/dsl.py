"""L'en-tête d'un script de workflow : le lire, et en écrire un neuf.

Module PUR : aucun accès au dépôt. Il n'écrit et ne lit que du texte, et c'est le
PARSEUR DU MOTEUR qui le relit — jamais une expression régulière maison. Même règle, et
même raison, que `miles.workflowevents.dsl` : on lit exactement ce que le moteur lira.

Ce module ne lit que l'EN-TÊTE — nom, libellé, version, inclusions, nombre d'états.
C'est ce qu'une liste montre. L'écriture des états et des transitions est une autre
affaire, et elle a sa story.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from urban_workflow.dsl.parser import WorkflowScriptParser

from miles.workflowevents.dsl import DslProblem


@dataclass(frozen=True)
class Header:
    """Ce qu'un script complet annonce avant ses états."""

    name: str
    # Le `DESCRIPTION` du script, déquoté ; None s'il n'en porte pas — la grammaire le
    # rend facultatif, et un workflow sans libellé n'est pas un brouillon.
    label: str | None
    # Le `VERSION` du script, tenu par CELUI QUI ÉCRIT et non par Miles : c'est une
    # version fonctionnelle du comportement, pas le numéro de révision d'un document.
    # D'où l'absence de `.meta.yaml` ici, à la différence d'un modèle.
    version: int | None
    # Les noms de FICHIER que le script `INCLUDE`, dans l'ordre écrit.
    includes: tuple[str, ...] = field(default=())
    # Combien d'états il déclare. Un compte et non la liste : la liste est l'objet de
    # l'écran d'écriture, pas de la liste des workflows.
    states: int = 0


class ScriptError(ValueError):
    """Le script ne se relit pas : TOUS les manquements, pas seulement le premier."""

    def __init__(self, problems: list[DslProblem]) -> None:
        super().__init__(f"{len(problems)} manquement(s) dans le script de workflow")
        self.problems = tuple(problems)


def read_header(text: str) -> Header:
    """L'en-tête d'un script complet ; lève `ScriptError`.

    Lu de l'ARBRE et non du visiteur, et c'est une mesure du 16/11/2026 : le visiteur
    `build()` un script complet, donc le faire visiter seul validerait un document dont
    les types d'event vivent dans des `INCLUDE` qu'on n'a pas visités. Or c'est le cas
    NORMAL ici — les types d'event de Miles sont dans les artefacts de périmètre.
    L'arbre, lui, porte l'en-tête sans rien exiger d'autre.
    """
    parser = WorkflowScriptParser.parse_string(text, "")
    if parser.errors:
        raise ScriptError([DslProblem(e.line, e.column, e.message) for e in parser.errors])
    if parser.is_fragment:
        # Un `FRAGMENT` est l'artefact de déclaration d'un périmètre, pas un workflow.
        # Le laisser passer ferait apparaître un référentiel de périmètre dans la liste
        # des workflows, avec un nom qui ne désigne aucun comportement.
        raise ScriptError([DslProblem(1, 0, "un workflow est un script complet, pas un FRAGMENT")])
    full = parser.tree.script_full()
    if full is None:  # pragma: no cover — sans erreur de syntaxe, l'un des deux existe
        raise ScriptError([DslProblem(1, 0, "script illisible")])
    version = full.versionNumber
    comment = full.comment()
    return Header(
        name=full.key().getText(),
        label=unquoted(comment.getText()) if comment is not None else None,
        version=int(version.getText()) if version is not None else None,
        includes=tuple(parser.includes),
        states=len(full.define_state_statement()),
    )


def render_new(name: str, label: str) -> str:
    """Un script complet MINIMAL, et il est chargeable tel quel.

    Mesuré le 16/11/2026 sur `urban-workflow 0.4.0` : `NAME <clef>` seul se relit sans
    erreur et se visite sans refus. C'est ce qui permet de créer un workflow en deux
    temps — l'identité ici, le comportement sur son écran — sans poser dans le dépôt un
    fichier qui ferait échouer le chargement de tout le répertoire entre les deux.

    La règle du script complet exige zéro déclaration propre (`*` et non `+`) depuis une
    extension de l'amont du 13/11/2026, faite pour qu'un workflow puisse tirer tout son
    référentiel de ses `INCLUDE` : sans elle, un script neuf était inécrivable.
    """
    return f"NAME {name}\nDESCRIPTION {quoted(label)}\n"


def quoted(label: str) -> str:
    """Un libellé entre quotes simples ; `''` est l'échappement d'une apostrophe.

    Un libellé VIDE n'est pas écrivable — `''` est une erreur de lexer, mesurée sur les
    types d'event le 14/11/2026 — donc un workflow a toujours un libellé à la création,
    et c'est tenu à la saisie.
    """
    return "'" + label.replace("'", "''") + "'"


def unquoted(text: str) -> str:
    """L'inverse de `quoted`, pour une `CHAR_STRING` rendue par l'arbre.

    Refait ici plutôt qu'importé : la fonction du moteur (`dsl.parser._unquote`) est
    privée, et dépendre du privé d'un paquet se casse à une montée sans rien annoncer.
    """
    text = text.strip()
    if len(text) >= 2 and text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    return text
