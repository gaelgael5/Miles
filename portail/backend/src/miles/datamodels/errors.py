"""Les deux refus que la lecture et l'écriture d'un modèle partagent.

Dans leur propre module, et non dans le service : l'écriture les lève, la surface MCP et
les routes les attrapent, et le service les lève aussi. Les laisser dans le service ferait
dépendre de lui tout ce qui ne veut qu'un nom d'erreur — et une importation circulaire dès
que l'écriture en sort.
"""

from __future__ import annotations


class ModelNotFoundError(Exception):
    pass


class ModelInUseError(Exception):
    def __init__(self, users: list[str]) -> None:
        super().__init__(f"référencé par {len(users)} modèle(s)")
        self.users = users
