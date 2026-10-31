from __future__ import annotations

from dataclasses import dataclass

from miles.workshop.trads import Context

# Repère par défaut de « très faible couverture », en pour cent. Une culture active sous
# ce taux est déjà visible par des utilisateurs réels, à qui l'écran affiche la culture
# par défaut du workspace : ça se signale (story 82e60880, critère 8).
#
# Configurable (`MILES_TRADS_LOW_COVERAGE_PERCENT`) et non codé en dur : le taux au-dessous
# duquel on s'alarme dépend du parc et du moment — une installation qui démarre ses
# traductions verrait sinon toutes ses langues en alerte, et apprendrait à ne plus regarder.
DEFAULT_LOW_PERCENT = 50


@dataclass(frozen=True)
class CultureCoverage:
    """Ce qu'une culture du workspace a de traduit sur la branche regardée."""

    culture: str
    translated: int
    missing: int
    # La culture par défaut du workspace : celle sans valeur de laquelle une clé ne peut
    # pas exister. Ce n'est PAS `en-US` — `en-US` n'est que la culture posée à la création
    # d'un workspace, et celui dont la culture par défaut est `fr-FR` doit voir `fr-FR` à
    # cent pour cent et peut légitimement afficher `en-US` à douze pour cent (critère 6).
    is_default: bool
    # Sous le seuil, donc à signaler. JAMAIS pour la culture par défaut : un manque chez
    # elle n'est pas un travail de traduction en retard, c'est une incohérence du dépôt.
    low: bool
    # Des clés n'ont pas de valeur dans la culture par DÉFAUT. Toujours faux pour les
    # autres : chez elles, un manque est l'état normal d'une clé qu'on vient d'ajouter.
    inconsistent: bool


@dataclass(frozen=True)
class Coverage:
    """La couverture de la branche : d'abord l'ensemble, puis contexte par contexte."""

    # La branche RÉELLEMENT lue, et non celle demandée : deux branches n'ont pas les mêmes
    # clés, et un écran qui ne dit pas laquelle il montre fait prendre l'une pour l'autre
    # (critère 11). C'est le dépôt qui la nomme, pas le paramètre d'appel.
    branch: str
    default: str
    keys: int
    # Le seuil appliqué, rendu avec le résultat : l'écran annonce le signalement AVEC sa
    # borne, sans quoi « couverture très basse » ne veut rien dire de vérifiable.
    threshold: int
    cultures: list[CultureCoverage]
    contexts: list[Context]


def rolled_up(
    contexts: list[Context],
    default: str,
    cultures: tuple[str, ...],
    *,
    branch: str,
    threshold: int,
) -> Coverage:
    """Somme les comptes des contextes pour obtenir la couverture de l'installation.

    Une somme et non un index : le dépôt fait foi, et un index de couverture stocké à
    côté pourrait le contredire — il faudrait alors choisir lequel croire. Les contextes
    partitionnent les clés (un slug vit dans un contexte et un seul), donc la somme est
    exacte, pas une estimation.
    """
    keys = sum(c.keys for c in contexts)
    rows = []
    for culture in cultures:
        translated = sum(c.translated.get(culture, 0) for c in contexts)
        is_default = culture == default
        rows.append(
            CultureCoverage(
                culture=culture,
                translated=translated,
                missing=keys - translated,
                is_default=is_default,
                # Comparaison STRICTE, et en produit en croix pour rester entière : au
                # seuil exact on ne signale pas, et une branche sans aucune clé ne
                # signale rien non plus — `0 < 0` est faux, donc une installation qui
                # n'a pas commencé ne voit pas toutes ses langues en alerte. Un
                # `keys > 0` ajouté ici ferait croire à une seconde garde alors qu'il ne
                # peut rien retirer : mesuré par injection, il était inerte.
                low=not is_default and translated * 100 < threshold * keys,
                inconsistent=is_default and translated < keys,
            )
        )
    return Coverage(
        branch=branch,
        default=default,
        keys=keys,
        threshold=threshold,
        cultures=rows,
        contexts=contexts,
    )
