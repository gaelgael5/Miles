"""Les sources que la version servie déclare : ce que la stack expose en entrée.

Lecture seule, et c'est structurel : une source est du paramétrage versionné, choisi dans
le module de paramétrage. Une route qui la changerait ici créerait une seconde vérité sur
ce que la stack reçoit, et `git revert` ne la défairait pas.

Ce module ne juge pas une déclaration fautive : il dit laquelle est lisible et laquelle ne
l'est pas. Le diagnostic de saisie est l'affaire du module de paramétrage, qui le rend à
qui édite ; ici, une déclaration illisible se signale et n'expose rien.
"""

from __future__ import annotations

from dataclasses import dataclass

from miles_socle.parametrage.refs import ReadFile
from miles_socle.parametrage.sources import (
    ROOT,
    SourceDoc,
    names_in,
    read_source,
    source_path,
)


@dataclass(frozen=True)
class DeclaredSources:
    """Ce que la version servie déclare, et ce qu'elle déclare mal.

    Les deux ensemble, jamais l'une sans l'autre : écarter silencieusement une
    déclaration illisible ferait chercher une source absente alors qu'elle est là, et
    fautive. C'est la leçon de la matérialisation des storages, où un refus muet aurait
    laissé croire qu'un storage n'était pas déclaré.
    """

    readable: dict[str, SourceDoc]
    unreadable: tuple[str, ...]

    @property
    def names(self) -> tuple[str, ...]:
        """Tous les noms déclarés, lisibles ou non, dans l'ordre.

        Une source illisible est bien DÉCLARÉE : un octroi qui la désigne n'est pas un
        octroi vers l'inconnu, et le refuser à l'écriture enverrait corriger le mauvais
        objet. Ce qu'elle n'expose pas, ce sont ses méthodes — et c'est le point
        d'entrée qui le dira.
        """
        return tuple(sorted((*self.readable, *self.unreadable)))


async def file_declared_sources(read: ReadFile, paths: list[str]) -> DeclaredSources:
    """Lit `sources/*.yaml` dans l'arbre servi. Un arbre vide ne déclare rien.

    La lecture est INJECTÉE, comme pour les storages : ce module se prouve alors sans
    arbre git ni base, ce qui est exactement ce qu'on veut d'un calcul dont une erreur
    ouvrirait une porte qu'aucune version ne déclare.
    """
    readable: dict[str, SourceDoc] = {}
    unreadable: list[str] = []
    for name in names_in(paths):
        doc = read_source(await read(source_path(name)))
        if doc is None or doc.name != name:
            # Le nom porté par la déclaration doit être celui du fichier : deux noms pour
            # un même objet feraient qu'une adresse d'ingestion et un octroi ne
            # désigneraient pas la même source.
            unreadable.append(name)
            continue
        readable[name] = doc
    return DeclaredSources(readable, tuple(unreadable))


__all__ = ["ROOT", "DeclaredSources", "file_declared_sources"]
