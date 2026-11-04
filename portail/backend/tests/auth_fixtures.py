"""Matériel de test de l'authentification, désormais porté par le socle.

Ce module ne fait plus que réexporter : `BASE_ENV`, `write_env`, les doublures de session
et d'horloge sont les mêmes pour les trois produits, et la table des sessions comme la
forme du `.env` appartiennent au socle. Une copie par produit dérive de ce qu'elle imite
au premier changement de requête.

Il est conservé plutôt que supprimé pour que les quinze fichiers de test qui l'importent
restent inchangés : un refactoring ne réécrit pas les tests.
"""

from __future__ import annotations

from miles_socle.testing import ADMIN_PASSWORD, BASE_ENV, FakeClock, FakeSessionDb, write_env

__all__ = ["ADMIN_PASSWORD", "BASE_ENV", "FakeClock", "FakeSessionDb", "write_env"]
