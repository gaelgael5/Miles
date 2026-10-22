# Leçons — Miles

Erreurs corrigées devenues règles (voir skill `self-improvement`).

- [tests/intégration] Un commit qui change la forme d'une réponse partagée (ex. `/api/auth/me`) se valide sur la suite d'intégration COMPLÈTE de test1, pas sur une sélection `-k` : le parcours OIDC réel la comparait à l'identique et a cassé après le push de 3e36815. Avant de choisir une sélection, chercher (`grep`) tous les tests qui lisent la forme modifiée.
