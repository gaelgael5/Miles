# Leçons — Miles

Erreurs corrigées devenues règles (voir skill `self-improvement`).

- [tests/intégration] Un commit qui change la forme d'une réponse partagée (ex. `/api/auth/me`) se valide sur la suite d'intégration COMPLÈTE de test1, pas sur une sélection `-k` : le parcours OIDC réel la comparait à l'identique et a cassé après le push de 3e36815. Avant de choisir une sélection, chercher (`grep`) tous les tests qui lisent la forme modifiée.
- [backlog] Avant de recommander un ticket, lire son corps, pas seulement son titre et son statut : 111b781e et a883a94d étaient « à faire » mais remplacés le 22/10 par les chaînes de transformations (bandeau « Remplacé — à clore par Gael »).
- [frontend] Un composant tiers lourd (Monaco, JSONJoy) se vérifie dans un vrai navigateur avant livraison, pas seulement sous jsdom : les tests verts cachaient des travailleurs jamais créés (API de Monaco changée en 0.53), un formulaire imbriqué qui rechargeait la page et un plantage sur un YAML en cours de frappe. Méthode : Chromium de test1 (`/function`), frontend construit, API simulée par interception des requêtes.
- [tests/intégration] Un service ajouté dans `app.py` (état `app.state.*`, types d'event) se câble AUSSI dans `tests/integration/git_stack.py`, qui monte l'application à la main : sans lui, chaque test d'intégration du service tombe en `KeyError` (story 7fa00f56, 22 tests rouges). Après tout ajout à `app.py`, `grep` du service voisin dans `tests/integration/`.
