"""Partitionnement à la journée et purge par rétention, pour les journaux.

Ce qui est ici est ce dont la divergence serait un défaut : la forme des partitions, leurs
bornes, et le calcul de ce qui a expiré. Trois journaux les veulent — les events des trois
produits, les appels d'ingestion, les messages MQTT — et deux n'existent pas encore.

**Ce qui reste au produit** : les MIGRATIONS. Le socle n'en porte aucune (décision du
27/10/2026), donc chaque produit déclare ses tables partitionnées, et le socle ne fait que
les entretenir. Le nom des tables n'est pas écrit ici en dur pour la même raison : il est
passé par l'appelant.

**Pourquoi la purge supprime des partitions et non des lignes** : un journal à rétention
glissante efface tous les jours. Un `DELETE` laisse les pages à récupérer et fragmente
l'index ; retirer une partition est immédiat et ne touche pas le reste. C'est la décision
du 18/10/2026, et elle a une conséquence mesurée le 03/11/2026 : elle est INCOMPATIBLE avec
une clé étrangère vers la table partitionnée, PostgreSQL refusant de retirer une partition
dont une contrainte dépend. Voir `partitions.py`.
"""
