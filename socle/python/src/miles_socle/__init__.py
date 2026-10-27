"""Socle technique partagé par les produits Miles : amorçage, OIDC, sessions,
cultures, secrets, journal d'events et accès PostgreSQL.

Ne contient aucun SQL : le schéma reste l'affaire de chaque produit (décision du
27/10/2026). Ne doit importer aucun paquet de produit — la frontière est tenue par
`tests/architecture`.
"""
