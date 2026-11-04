from __future__ import annotations

from miles.workspaces.model import WorkspaceConflictError


class SlugTakenError(WorkspaceConflictError):
    def __init__(self, slug: str) -> None:
        super().__init__("slug_pris")
        self.slug = slug


class UnknownCultureError(WorkspaceConflictError):
    """Valeur reçue pour une culture que ce workspace ne retient pas.

    Refusé plutôt qu'ignoré : écrire un fichier pour une culture hors des réglages
    créerait une langue que l'écran ne montre pas, et personne ne la retrouverait.
    """

    def __init__(self, culture: str) -> None:
        super().__init__("culture_hors_workspace")
        self.culture = culture


class KeyUnknownError(WorkspaceConflictError):
    def __init__(self, slug: str) -> None:
        super().__init__("cle_inconnue")
        self.slug = slug


class ConcurrentEditError(WorkspaceConflictError):
    """La branche a bougé pendant l'écriture : rien n'est poussé, l'appelant rejoue.

    Le push se fait sur un bail (`--force-with-lease`) : deux saisies concurrentes sur la
    même clé ne peuvent pas s'écraser en silence (critère 19). La seconde est refusée, et
    c'est ce refus que l'écran montre — pas une valeur disparue.
    """

    def __init__(self) -> None:
        super().__init__("branche_a_bouge")
