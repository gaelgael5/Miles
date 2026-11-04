"""Clés d'API de service : la mécanique de la clé, commune à DEUX produits.

Extrait au socle le 02/11/2026, deuxième usage. Le portail en émet pour atteindre sa
surface MCP (story 3429986c) ; le module d'environnement en émet pour que des systèmes
tiers déposent des données sur ses points d'entrée d'ingestion — décision de Gael du
02/11/2026 : « l'environnement porte une page pour gérer les clés d'api ».

**Ce qui est ici, et pourquoi exactement cela** : la fabrication de la clé, son
empreinte, le préfixe affiché et la comparaison en temps constant. Ce sont les gestes
dont une divergence entre deux produits serait un DÉFAUT DE SÉCURITÉ silencieux — un
hachage différent, une comparaison qui fuit, un préfixe trop long. Rien ne signalerait
l'écart : les deux produits continueraient de fonctionner.

**Ce qui reste au produit** : la table et sa migration (le socle ne porte aucune
migration), les requêtes qui la lisent, et surtout ce qu'un OCTROI désigne — un workspace
avec un niveau d'accès pour le portail, une source d'ingestion pour l'environnement.
Les deux n'ont ni la même forme ni le même sens, et les réunir derrière une abstraction
obligerait chacun à porter la notion de l'autre.
"""
