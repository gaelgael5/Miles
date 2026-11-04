"""La forme des partitions journalières, et ce qui a expiré. Calcul PUR, sans base.

Séparé des requêtes parce qu'une erreur ici SUPPRIME un jour de journal qu'il fallait
garder : ce calcul doit s'éprouver sans base, en avançant une horloge injectée, et non en
attendant minuit.

**Les bornes sont en UTC**, et c'est mesuré et non supposé : la base est en `Etc/UTC`
(`0001_socle.sql`), et un `timestamptz` comparé à une borne `date` est ramené au fuseau de
la session. Un produit qui changerait le fuseau de sa session déplacerait donc les
frontières de ses journées ; un test le constate.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

# Combien de jours sont posés À L'AVANCE. Mesuré le 03/11/2026 : une insertion dont la
# partition manque n'est pas rangée ailleurs, elle ÉCHOUE (`23514, no partition of
# relation … found for row`). Sept jours laissent une semaine entière pour qu'un
# déclencheur manqué soit remarqué, et la réparation à l'écriture (voir `events/journal.py`)
# couvre le cas où rien n'a tourné depuis plus longtemps.
DAYS_AHEAD = 7

# Le suffixe que NOUS posons. Une partition qui ne le porte pas n'est pas de nous, et la
# purge n'y touche jamais — même principe que `is_ours` des tables de storage : on ne
# supprime que ce qu'on a créé, et un écart se signale au lieu d'être réparé.
_SUFFIX = "%Y%m%d"
_SUFFIX_RE = re.compile(r"^(\d{8})$")


def partition_name(table: str, day: date) -> str:
    return f"{table}_{day.strftime(_SUFFIX)}"


def partition_day(table: str, name: str) -> date | None:
    """Le jour qu'une partition porte, ou nul si ce n'est pas une des nôtres."""
    if not name.startswith(f"{table}_"):
        return None
    reste = name[len(table) + 1 :]
    if _SUFFIX_RE.match(reste) is None:
        return None
    try:
        return datetime.strptime(reste, _SUFFIX).replace(tzinfo=UTC).date()
    except ValueError:
        # « 20261332 » a la bonne forme et n'est pas une date : ce n'est pas une des nôtres.
        return None


def create_partition(table: str, day: date) -> str:
    """Le `CREATE` d'une partition, TOLÉRANT au déjà-là.

    `IF NOT EXISTS` ici, à l'inverse de la création d'index des tables de storage, où la
    tolérance se décidait sur le nom et pouvait faire taire une création légitime. Ici le
    nom EST la date et la table parente est nommée : rejouer ne peut rien recouvrir
    d'autre, et c'est ce qui rend l'entretien idempotent (mesuré, rend un `NOTICE`).
    """
    nom = partition_name(table, day)
    # Les bornes portent le fuseau EXPLICITEMENT (`+00:00`). Sans lui, une borne `date`
    # comparée à un `timestamptz` serait ramenée au fuseau de la SESSION : la base est en
    # `Etc/UTC` (`0001_socle.sql`), mais s'y fier ferait déplacer les frontières de journée
    # le jour où quelqu'un pose un `SET timezone` quelque part. Ici, rien à savoir.
    return (
        f'CREATE TABLE IF NOT EXISTS "{nom}" PARTITION OF "{table}" '
        f"FOR VALUES FROM ('{_bound(day)}') TO ('{_bound(day + timedelta(days=1))}')"
    )


def _bound(day: date) -> str:
    return f"{day.isoformat()} 00:00:00+00:00"


def drop_partition(table: str, day: date) -> str:
    # `IF EXISTS` : la purge rejouée sur une partition déjà retirée ne doit pas tomber en
    # erreur (critère 6 du ticket 8e86afbc), et PostgreSQL n'en rend qu'un `NOTICE`.
    return f'DROP TABLE IF EXISTS "{partition_name(table, day)}"'


def days_to_ensure(today: date, ahead: int = DAYS_AHEAD) -> list[date]:
    """Aujourd'hui, et les `ahead` jours suivants."""
    if ahead < 0:
        raise ValueError("ahead négatif")
    return [today + timedelta(days=n) for n in range(ahead + 1)]


def expired_days(present: set[date], today: date, retention_days: int | None) -> list[date]:
    """Les jours à retirer pour qu'il reste EXACTEMENT les `retention_days` derniers.

    **Rétention absente : on ne retire rien.** Un paramètre oublié doit laisser le journal
    grossir, pas l'effacer — un disque qui se remplit se voit et se répare, un journal
    effacé ne revient pas (critère 5 du ticket 8e86afbc).

    Les jours À VENIR ne sont jamais retirés : ce sont les partitions posées d'avance, et
    les compter comme expirées ferait défaire à chaque passage ce que le passage vient de
    poser.
    """
    if retention_days is None:
        return []
    if retention_days < 1:
        raise ValueError("retention_days doit valoir au moins 1 jour")
    # N jours conservés = aujourd'hui inclus, donc la plus ancienne journée gardée est
    # `today - (N - 1)`. Avec N = 1, il ne reste qu'aujourd'hui.
    plus_ancienne = today - timedelta(days=retention_days - 1)
    return sorted(jour for jour in present if jour < plus_ancienne)
