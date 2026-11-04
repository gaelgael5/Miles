# Module d'enrôlement

Deuxième des trois produits de Miles (cadrage `terminal-pr`, *Découpage en trois produits*) :
référentiel des devices, enrôlement des installations, appariement des environnements.

**Cette coquille ne porte aucun métier** — elle démarre, se déploie et se connecte. Le
référentiel, l'enrôlement et l'appariement viennent avec leurs propres tickets.

Stack, base et administration propres au produit. Rien n'est partagé avec le portail hors
le code du socle (`socle/python`, `socle/web`) : ni la base, ni le compte d'amorçage, ni le
secret de session. La frontière est tenue par `tests/architecture` à la racine du dépôt.

## Gestes du quotidien

```bash
cd enrolement/backend  && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd enrolement/frontend && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
enrolement/dev-deploy.sh                      # livrer, PORTAL_TOKEN sur stdin, jamais en argv
enrolement/scripts/run-integration-tests.sh   # campagne, à lancer détachée
```

Le port publié par défaut est **8081** : le portail occupe 8080 sur la même machine de test.
