"""L'évaluation JSLT, au socle depuis le 3 novembre 2026 (enabler `b2a215ee`).

Deuxième usage : le module d'environnement transforme les objets qu'il reçoit avant de les
écrire dans un storage (story `d680e811`), après le module de paramétrage qui écrit et
éprouve les templates. Ce qui voyage ici est l'ÉVALUATION — l'arbre, le profil d'écriture,
le registre des fonctions admises, l'application d'une chaîne d'étapes.

**`urban-json` est un EXTRA du socle, pas une dépendance** : le module d'enrôlement ne
transforme rien, et le `pyproject.toml` du socle porte la raison de ne pas lui imposer des
paquets dont il n'a aucun usage. Importer ce sous-paquet sans l'extra échoue à l'import,
au démarrage, et non sur un chemin de données.

Ce qui RESTE au module de paramétrage : l'écriture d'une chaîne et son diagnostic de
saisie, le catalogue servi à l'éditeur, la conformité d'une chaîne à ses modèles. Même
frontière que celle tracée le 02/11/2026 pour les sources et les storages — seule la
lecture et l'exécution voyagent, la saisie reste chez qui la sert.
"""
