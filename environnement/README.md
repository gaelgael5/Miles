# Module d'environnement

Troisième des trois produits de Miles (cadrage `terminal-pr`, *Découpage en trois
produits*) : une stack et une base **par environnement déployé**.

**Réduit à ce que l'appariement exige** (ticket 8c95ecc7) : le module détient une paire de
clés engendrée chez lui, garde sa clé privée, émet et vérifie des appels signés. Le
back-office d'environnement — objets métier, entrées, sorties, site, APIs, paramétrage
servi — viendra à son tour, et plusieurs de ses questions sont encore ouvertes au cadrage.

Stack, base et administration propres au produit. Rien n'est partagé avec les deux autres
produits hors le code du socle (`socle/python`, `socle/web`) : ni la base, ni le compte
d'amorçage, ni le secret de session. La frontière est tenue par `tests/architecture` à la
racine du dépôt.

## Gestes du quotidien

```bash
cd environnement/backend  && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd environnement/frontend && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
environnement/dev-deploy.sh                      # livrer, PORTAL_TOKEN sur stdin, jamais en argv
environnement/scripts/run-integration-tests.sh   # campagne, à lancer détachée
```

Le port publié par défaut est **8082** : le portail occupe 8080 et le module
d'enrôlement 8081 sur la même machine de test.

## L'identité du module

Le module engendre **au premier démarrage** une paire de clés Ed25519 qu'il garde :

- la **clé privée** est rangée dans la table des secrets du produit, chiffrée par
  `MILES_SECRETS_KEY`, et son usage déclaré interdit à la base de la supprimer ;
- elle **ne se régénère jamais** — ni au redéploiement, ni au redémarrage. La régénérer
  casserait l'appariement et imposerait de réaffecter les devices à la main ;
- la **clé publique** du module d'enrôlement apparié se déclare par
  `PUT /api/identity/peer`, en attendant le protocole d'appariement (ticket `6a0daab6`).

`POST /api/peer/ping` est la seule route authentifiée **par signature** et non par
session : c'est l'échange qui dit que l'appariement est vivant et que les clés concordent.
