"""Module d'environnement de Miles : une stack et une base par environnement déployé.

Troisième des trois produits du dépôt (cadrage `terminal-pr`, « Découpage en trois
produits »). Stack, base et administration propres : rien n'est partagé avec les deux
autres produits hors le code du socle, et la frontière est tenue par `tests/architecture`.

RÉDUIT À CE QUE L'APPARIEMENT EXIGE (ticket 8c95ecc7) : sa paire de clés, sa persistance
et ses appels signés. Le back-office d'environnement proprement dit — objets métier,
entrées, sorties, site, APIs, paramétrage servi — viendra à son tour. Monter sa coquille
complète maintenant reviendrait à trancher en codant plusieurs questions que le cadrage
laisse OUVERTES : où vit la base d'un environnement, le mécanisme de vague, le registre
des stacks déployées.
"""
