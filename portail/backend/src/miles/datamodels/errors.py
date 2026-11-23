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
        # « document » et non « modèle » : depuis le bug `6ed86d6b`, un storage, une
        # source ou une chaîne empêchent aussi la suppression.
        super().__init__(f"désigné par {len(users)} document(s)")
        self.users = users
