"""La garde contre le service câblé dans l'application et oublié dans le montage de test.

`LESSONS.md` porte la même panne DEUX fois, aux 22 et 24/10/2026 : un service ajouté dans
`app.py` et oublié dans le montage à la main des tests d'intégration fait tomber tous les
tests de ce service, sur une erreur qui ne parle pas de lui. 22 tests rouges la première
fois, 15 la seconde — « alors que cette leçon existait déjà ». Avec trois produits, l'oubli
était possible en cinq endroits.

Lu par `ast`, sans importer ni exécuter le code, pour la même raison que le test de
frontière : la vérification doit tourner sur le poste de développement, sans base, sans
courtier et sans environnement de produit installé. C'est aussi ce qui la rend assez rapide
pour être un test unitaire — donc lancée à chaque fois, et non une fois par campagne.

LIMITE ASSUMÉE, et ce n'est pas un oubli : seules sont vues les affectations
`<quelque chose>.state.<nom> = …` et celles passant par un alias LOCAL de `.state`
— `state = portal.app.state` puis `state.<nom> = …`, le style du portail. Un
`setattr(app.state, nom, …)`, une clef calculée ou un alias construit autrement
échapperaient à cette lecture. Les trois produits emploient aujourd'hui l'une des deux
formes reconnues ; le jour où ce n'est plus vrai, cette garde cesse de garder en silence —
d'où ce paragraphe, plutôt qu'une confiance tacite.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping
from pathlib import Path

# Nom de la fonction de durée de vie dans `app.py`, par convention dans les trois produits.
# Ce qui est posé AILLEURS dans ce fichier l'est par `build_app`, que tout montage de test
# appelle : ces services sont donc présents par construction et n'ont pas à être comparés.
DEFAULT_LIFESPAN = "lifespan"


def file_wirings(fichier: Path) -> frozenset[str]:
    """Les noms posés sur `app.state` par un fichier, où que ce soit dans le fichier."""
    return _wirings(ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier)))


def file_lifespan_wirings(fichier: Path, lifespan: str = DEFAULT_LIFESPAN) -> frozenset[str]:
    """Les noms posés sur `app.state` DANS la durée de vie de l'application.

    Lève si la fonction est introuvable : une garde qui rendrait l'ensemble vide passerait
    au vert sans rien avoir comparé, et c'est le vert le plus trompeur qui soit.
    """
    arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.AsyncFunctionDef | ast.FunctionDef) and noeud.name == lifespan:
            return _wirings(noeud)
    raise RuntimeError(
        f"fonction « {lifespan} » introuvable dans {fichier} : la garde ne compare rien. "
        "Si la durée de vie a changé de nom, passer le nouveau nom à cette garde."
    )


def resolve_missing_wirings(
    app_module: Path, harnais: Iterable[Path], lifespan: str = DEFAULT_LIFESPAN
) -> frozenset[str]:
    """Ce que la durée de vie pose et qu'AUCUN montage de test ne pose."""
    montes: set[str] = set()
    for fichier in harnais:
        montes |= file_wirings(fichier)
    return file_lifespan_wirings(app_module, lifespan) - montes


def assert_harness_wires_everything(
    app_module: Path,
    harnais: Iterable[Path],
    lifespan: str = DEFAULT_LIFESPAN,
    absents_admis: Mapping[str, str] | None = None,
) -> None:
    """Échoue en NOMMANT les services oubliés, au lieu de laisser la panne se découvrir.

    `absents_admis` nomme les services qu'aucun montage de test n'a à câbler, chacun avec
    sa raison écrite à côté. Ce n'est pas un trou dans la garde : la liste est FERMÉE par
    défaut, donc un service ajouté demain et oublié fait rougir ce test ; pour le taire, il
    faut l'écrire ici et dire pourquoi. Une raison vide est refusée.
    """
    harnais = list(harnais)
    admis = dict(absents_admis or {})
    sans_raison = sorted(nom for nom, raison in admis.items() if not raison.strip())
    if sans_raison:
        raise AssertionError(
            "services déclarés absents sans raison : "
            + ", ".join(sans_raison)
            + ". Un service qu'aucun montage ne câble se justifie, ou se câble."
        )
    manquants = resolve_missing_wirings(app_module, harnais, lifespan) - set(admis)
    inutiles = sorted(set(admis) - file_lifespan_wirings(app_module, lifespan))
    if inutiles:
        # Une exception qui ne sert plus désigne un service disparu : la laisser en place
        # ferait taire un oubli futur sur un nom recyclé.
        raise AssertionError(
            "exceptions devenues inutiles, à retirer : "
            + ", ".join(inutiles)
            + ". Ces services ne sont plus posés par la durée de vie."
        )
    if manquants:
        raise AssertionError(
            "services posés par la durée de vie de l'application et absents de tout montage "
            f"de test : {', '.join(sorted(manquants))}.\n"
            f"Application : {app_module}\n"
            f"Montages lus : {', '.join(str(f) for f in harnais)}\n"
            "Un test d'intégration qui emploie l'un de ces services tombera sur une erreur "
            "qui ne parle pas de lui (LESSONS.md, 22 puis 24/10/2026). Les câbler dans le "
            "montage — ou, s'ils n'ont volontairement pas à y être, le dire en commentaire "
            "à l'endroit où ce test les attend."
        )


def _wirings(noeud: ast.AST) -> frozenset[str]:
    affectations = [sous for sous in ast.walk(noeud) if isinstance(sous, ast.Assign)]
    # Premier passage : les alias locaux de `.state`. Le portail écrit
    # `state = portal.app.state` puis `state.secrets = …`, et sans ce passage les
    # vingt-quatre services de son harnais git passeraient pour non câblés.
    alias = {
        cible.id
        for sous in affectations
        if isinstance(sous.value, ast.Attribute) and sous.value.attr == "state"
        for cible in sous.targets
        if isinstance(cible, ast.Name)
    }
    trouves: set[str] = set()
    for sous in affectations:
        for cible in sous.targets:
            if not isinstance(cible, ast.Attribute):
                continue
            porteur = cible.value
            # `<quelque chose>.state.<nom> = …`, ou `<alias>.<nom> = …`. Le nom de la
            # variable d'application n'est pas contraint : `app` dans les trois produits,
            # mais rien ici n'en dépend.
            if (isinstance(porteur, ast.Attribute) and porteur.attr == "state") or (
                isinstance(porteur, ast.Name) and porteur.id in alias
            ):
                trouves.add(cible.attr)
    return frozenset(trouves)
