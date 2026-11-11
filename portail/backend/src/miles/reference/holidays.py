"""Les jours fériés d'un pays : son fichier de règles, et ce que le moteur en calcule.

Module PUR, et c'est ce qui permet de l'éprouver entièrement : il ne connaît ni la base ni
HTTP, et le moteur n'y entre que par un protocole à une seule méthode. Demandé par Gael le
11/11/2026 — « voir le lien vers le fichier source qui contient les règles du pays [...]
mais également voir les jours calculés par l'application pour les 12 prochains mois ».

L'ASSOCIATION pays → fichier est en base (migration 0033, engendrée depuis le TOC de
calendarium) ; les RÈGLES, elles, vivent dans le dépôt de calendarium et c'est le paquet
installé qui les évalue. Rien n'est recopié : l'écran montre d'où vient la règle, et ce
qu'elle produit.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

# Ce que le TOC publie, et ce vers quoi un humain clique. Le paquet ne publie que l'URL
# BRUTE (`raw.githubusercontent.com`), qui rend du texte nu dans le navigateur ; la page
# GitHub est la même adresse sous une autre forme. Les deux préfixes sont écrits ici, et
# nulle part ailleurs, pour que la dérivation se lise d'un coup d'œil.
RAW_PREFIX = "https://raw.githubusercontent.com/"
PAGE_PREFIX = "https://github.com/"


class DatesSource(Protocol):
    """Le moteur de calendarium, réduit à ce que ce module lui demande.

    Un protocole et non la classe `Calendarium` : les tests de ce module n'ont pas à
    charger 111 fichiers de règles pour éprouver un découpage de fenêtre, et le jour où le
    paquet renomme une méthode, c'est ici — en un endroit — que l'écart se voit.
    """

    def get_dates(self, year: int, country: str) -> dict[dt.date, Any]: ...


class UnknownToEngineError(Exception):
    """La base associe ce pays à un fichier que le moteur installé ne porte pas.

    FAIL CLOSED, et un état possible plutôt qu'improbable : l'association vient de la
    migration 0033, engendrée depuis le TOC d'une version de calendarium, et le paquet
    installé peut être une AUTRE version. Une montée qui retire un pays du palier vérifié
    produirait exactement ce cas. Il se nomme donc, au lieu de laisser un `KeyError` sortir
    en 500 — un écran qui dit « règles indisponibles » envoie regarder la version du
    paquet, une erreur serveur n'envoie nulle part.
    """


@dataclass(frozen=True)
class HolidayRule:
    """Le fichier de règles d'un pays, tel que l'écran le montre.

    Les deux URL sortent ENSEMBLE : `source_url` est ce que le TOC publie et ce que la base
    porte — donc ce qui est vérifiable —, `page_url` est ce sur quoi on clique. Ne rendre
    que la seconde ferait disparaître la donnée d'origine de tout écran et de tout journal.
    """

    country: str
    source_url: str
    page_url: str


@dataclass(frozen=True)
class HolidayDay:
    """Un jour calculé : sa date légale, le jour réellement chômé, et ce qu'il est.

    `observed` est rendu MÊME quand il égale `date`, plutôt que laissé nul dans ce cas :
    un écran qui doit tester la nullité pour savoir quoi afficher finit par afficher
    « — » là où la réponse est « le même jour ».

    `free` dit si le jour est chômé. Toutes les périodes d'un fichier ne le sont pas : une
    commémoration peut être calculée sans être un jour de congé, et les confondre ferait
    annoncer fermé un point relais qui ouvre.
    """

    date: dt.date
    observed: dt.date
    name: str
    free: bool
    # Vrai quand le jour chômé n'est pas la date légale (report d'un dimanche au lundi,
    # typiquement). Dérivé plutôt que lu sur l'event : le paquet expose `is_shifted`, mais
    # rien ne l'engage à le garder — l'égalité des deux dates, elle, ne bougera pas.
    shifted: bool


def page_url(source_url: str) -> str:
    """La page GitHub navigable d'une URL brute de fichier.

    `raw.githubusercontent.com/<compte>/<dépôt>/<réf>/<chemin>` devient
    `github.com/<compte>/<dépôt>/blob/<réf>/<chemin>`. Vérifié sur le fichier de la France
    le 11/11/2026 : les deux adresses répondent.

    REPLI VOLONTAIRE, et ce n'est pas un bug : une URL qui ne porte pas le préfixe brut est
    rendue TELLE QUELLE. C'est un lien qui mène quelque part — l'URL que le TOC publie —
    là où une dérivation forcée produirait une adresse inventée et un 404. Le jour où
    l'auteur publie son TOC depuis un autre hôte, l'écran garde un lien qui marche.
    """
    if not source_url.startswith(RAW_PREFIX):
        return source_url
    reste = source_url[len(RAW_PREFIX) :]
    parts = reste.split("/", 3)
    if len(parts) < 4:
        # Pas assez de segments pour nommer un compte, un dépôt, une référence et un
        # chemin : on ne devine pas lequel manque.
        return source_url
    compte, depot, reference, chemin = parts
    return f"{PAGE_PREFIX}{compte}/{depot}/blob/{reference}/{chemin}"


def window(today: dt.date) -> tuple[dt.date, dt.date]:
    """Les 12 prochains mois : d'aujourd'hui au même jour l'an prochain, bornes incluses.

    Bornes INCLUSES, et le même jour de part et d'autre : « les 12 prochains mois » se lit
    comme un calendrier qu'on déroule, pas comme un intervalle de 365 jours — qui aurait
    fait sauter le 29 février d'une année bissextile traversée.

    Le 29 février est ramené au 28 quand l'année suivante ne le porte pas. Sans cette
    borne, l'écran rendrait 500 un jour tous les quatre ans, et le défaut ne se
    reproduirait pas le lendemain.
    """
    try:
        fin = today.replace(year=today.year + 1)
    except ValueError:
        fin = today.replace(year=today.year + 1, day=28)
    return today, fin


def days_in_window(
    dates: DatesSource, country: str, start: dt.date, end: dt.date
) -> list[HolidayDay]:
    """Les jours calculés dont la date légale OU le jour chômé tombe dans la fenêtre.

    **Par ANNÉE CIVILE, et non par `get_next_dates`**, qui existe pourtant et semble fait
    pour ça. Trois raisons mesurées sur le code du paquet (0.4.0) : cette méthode n'accepte
    aucune clé d'indexation, donc n'applique jamais la date observée ; son paramètre
    `regions` ne porte que les règles nationales par défaut ; et elle n'itère que sur les
    années de la fenêtre, donc une fête de fin d'année reportée sur la suivante n'est pas
    rapatriée. `get_dates` par année, elle, balaie l'année précédente et la suivante pour
    ses reports.

    **La fenêtre retient une date OU l'autre** : un jour férié du 31 décembre reporté au
    1er janvier est chômé DANS la fenêtre même si sa date légale la précède, et l'inverse
    est vrai à l'autre bout. Ne tester que la date légale aurait fait disparaître de
    l'écran le jour de congé qui s'y trouve.
    """
    vus: set[tuple[dt.date, dt.date, str]] = set()
    jours: list[HolidayDay] = []
    # UNE ANNÉE DE PART ET D'AUTRE, et ce n'est pas de la prudence : un report franchit la
    # frontière d'année DANS LES DEUX SENS. Une fête du 31 décembre peut être chômée le
    # 1er janvier (donc son année légale précède la fenêtre), et le DSL des règles porte un
    # opérateur de recul (`<<`) qui fait l'inverse. Relevé par un test le 11/11/2026 :
    # borné aux années de la fenêtre, ce balayage perdait le jour chômé qui s'y trouve —
    # exactement le défaut qu'on reproche à `get_next_dates` juste au-dessus.
    for annee in range(start.year - 1, end.year + 2):
        try:
            calcules = dates.get_dates(annee, country)
        except KeyError as exc:
            # Le moteur rend `KeyError` pour un pays qu'il ne connaît pas. Traduit ici, à
            # la frontière de la bibliothèque, pour que l'appelant n'ait pas à savoir
            # quelle exception le paquet a choisie.
            raise UnknownToEngineError(country) from exc
        for legale, identifie in calcules.items():
            for event in identifie.events:
                # `observed` peut être absent d'un event : on retombe sur la date légale,
                # qui est ce qu'un fichier sans règle de report décrit déjà.
                chome = getattr(event, "observed", None) or legale
                if not (start <= legale <= end or start <= chome <= end):
                    continue
                marque = (legale, chome, event.name)
                if marque in vus:
                    continue
                vus.add(marque)
                jours.append(
                    HolidayDay(legale, chome, event.name, bool(event.free), chome != legale)
                )
    # Ordonnés sur la date LÉGALE : c'est l'épine du calendrier, et le jour chômé s'y lit à
    # côté. Trier sur le jour chômé ferait bouger de place une ligne pour la seule raison
    # qu'elle est reportée, alors que c'est précisément ce que la colonne dit déjà.
    return sorted(jours, key=lambda j: (j.date, j.name))


@lru_cache(maxsize=1)
def bundled_dates() -> DatesSource:
    """Le moteur sur le référentiel EMBARQUÉ par le paquet installé.

    `bundled()` et non `from_toc()`, alors que c'est le TOC qui a produit l'association en
    base : le TOC se lit par le RÉSEAU, et un démarrage qui appelle GitHub échouerait là où
    le paquet porte déjà les mêmes fichiers. Le TOC a servi UNE fois, au moment d'engendrer
    la migration, où un humain relit ce qu'il produit.

    Construit UNE fois PAR PROCESSUS (`lru_cache`), et appelé depuis `build_app` — donc
    avant que la boucle ne serve : 102 ms et 111 fichiers lus, mesurés le 11/11/2026,
    contre 0,4 ms pour une année calculée ensuite. Deux raisons, et il faut les deux : une
    construction par requête poserait de l'entrée-sortie BLOQUANTE sur un chemin
    asynchrone, et une construction par `build_app` ferait payer ces 102 ms à chacun des
    tests d'intégration qui montent l'application.

    Le moteur est en lecture seule une fois bâti : le partager entre deux applications d'un
    même processus ne les fait pas se marcher dessus — son cache interne est indexé par
    (année, pays), et une année calculée vaut la même chose pour tout le monde.
    """
    from calendarium import Calendarium

    # Annoté puis rendu : le paquet n'embarque pas de marqueur `py.typed` (vérifié), donc
    # mypy voit `Any`. L'annotation locale est ce qui fait vérifier, ici et une seule fois,
    # que le moteur satisfait bien le protocole que ce module déclare.
    engine: DatesSource = Calendarium.bundled()
    return engine
