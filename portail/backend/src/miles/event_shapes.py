"""Les fragments de schéma que les types d'event du portail se partagent.

Un fichier et non une copie par module : `commit` et `branch` apparaissent dans plus de
vingt des soixante-et-un types d'ici — tout geste de l'atelier commet dans une copie de
travail et dit où. Vingt-quatre copies auraient divergé, et la première à relâcher la
forme du commit l'aurait relâchée pour elle seule, sans que rien ne le dise.

Ce qui reste au module, en revanche, c'est la FORME de chacun de ses types : ces
fragments sont un vocabulaire, pas un gabarit d'event.
"""

from __future__ import annotations

from typing import Any, Final

#: Un commit COMPLET, et la forme est contrainte parce que ces valeurs viennent toutes
#: d'un commit réel — de la forge ou d'une copie de travail. Un préfixe court ne se
#: récupère pas d'une forge, et deux commits pourraient le partager.
COMMIT: Final[dict[str, Any]] = {"type": "string", "pattern": r"^[0-9a-f]{40}$"}
#: Le nom de branche de la copie de travail où le geste a été commis.
BRANCH: Final[dict[str, Any]] = {"type": "string", "minLength": 1}
#: Un nom, un slug, un chemin : non vide, et le module dit lequel.
NAME: Final[dict[str, Any]] = {"type": "string", "minLength": 1}
#: Un compte d'objets touchés. Zéro admis : « rien n'a été retiré » est un résultat.
COUNT: Final[dict[str, Any]] = {"type": "integer", "minimum": 0}
#: Le geste de l'atelier : où il a commis, et sur quelle branche.
GESTURE: Final[dict[str, Any]] = {"commit": COMMIT, "branch": BRANCH}
