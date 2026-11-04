# Portail de configuration

Premier des trois produits de Miles. Il administre les **workspaces** et leur
paramétrage : modèles de données, contrats, chaînes de transformation JSLT, storages et
sources de données. Le paramétrage vit dans **git**, versionné et homologué ; la base
PostgreSQL ne porte que l'état du portail lui-même.

## Stack

`docker-compose.yml` — base PostgreSQL, back-office FastAPI, frontend Vite servi par
nginx, et un broker MQTT. Le déploiement passe **uniquement** par `./dev-deploy.sh`, sur
une machine de test, jamais par une construction ou un `docker run` à la main.

## Commandes

```bash
cd backend && uv sync
cd backend && uv run ruff check src tests && uv run mypy src && uv run pytest -v
cd frontend && npm ci && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
scripts/run-integration-tests.sh      # intégration PostgreSQL + Gitea — machine de test
./dev-deploy.sh                       # livrer
```

## Contrats publiés

`docs/contracts/` porte les contrats d'interface de CE produit, engendrés depuis le code
par `uv run miles-contracts`. Un test refuse qu'ils divergent.
