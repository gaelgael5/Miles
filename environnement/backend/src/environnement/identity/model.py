"""Ce que le module d'environnement tient EN PLUS d'un pair : l'environnement assigné.

Le reste — le pair unique, ses refus, les gestes de l'appariement et l'état du geste — est
au socle depuis le 29/10/2026 (`miles_socle.pairing`), parce qu'un deuxième produit en a
besoin : le module de paramétrage s'apparie au même module d'enrôlement, par le même
mécanisme (ticket ba44914b). Ne reste donc ici que ce dont l'autre n'a que faire.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

SIGNING_KEY_LABEL = "Clé privée de signature du module d'environnement"
# Ce que ce module répond dans l'échange de vivacité. Au produit, parce que c'est son nom.
MODULE_NAME = "environnement"


@dataclass(frozen=True)
class AssignedEnvironment:
    """L'environnement du référentiel de l'enrôlement auquel il nous a rattachés.

    Le seul nom qui fasse AUTORITÉ sur cet environnement : il est posé par un humain chez
    l'enrôlement, alors que `declared_name` est ce que cette stack dit d'elle-même. Les
    deux peuvent différer, et c'est celui-ci qui compte.

    `fetched_at` est DANS cette classe, et non à côté : une valeur venue d'un autre module
    ne s'affiche jamais sans la date à laquelle on l'a obtenue — faute de quoi un repli
    serait indiscernable d'une lecture fraîche. Les trois champs vivent et meurent
    ensemble, et la base le dit aussi : ils sont les trois colonnes obligatoires de
    `assigned_environment`, dont l'absence de LIGNE est le « jamais lu ».

    L'identifiant du référentiel n'y figure PAS : c'est la clé d'une autre base, et la
    ranger ici écrirait une relation que personne ne réconcilie.
    """

    slug: str
    label: str
    # NOTRE horloge, pas celle du pair. Les deux dérivent, et pour un affichage mieux vaut
    # la date dont on répond que celle qu'un autre annonce.
    fetched_at: datetime


@dataclass(frozen=True)
class AssignedEnvironmentView:
    """L'environnement rattaché tel que l'écran doit le montrer, fraîcheur comprise.

    Quatre cas, et les quatre se lisent différemment — c'est pourquoi `fresh` ne se déduit
    pas de `environment` :

    - frais avec valeur : ce que le pair vient de dire ;
    - frais SANS valeur : le pair répond qu'aucun environnement ne nous est rattaché.
      La valeur mémorisée est alors EFFACÉE — elle ne survit pas à une réponse fraîche qui
      la contredit ;
    - pas frais avec valeur : le pair est injoignable, on montre la dernière valeur connue
      et sa date, en disant qu'elle n'a pas pu être rafraîchie ;
    - pas frais SANS valeur : le pair est injoignable et on n'a jamais rien su. On le dit,
      plutôt que de montrer un vide qui se lirait « aucun environnement rattaché ».

    Les deux derniers cas ne diffèrent que par ce champ, et les confondre ferait annoncer
    « aucun environnement » à un administrateur dont le réseau est coupé.
    """

    environment: AssignedEnvironment | None
    fresh: bool
