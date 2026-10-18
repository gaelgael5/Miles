#!/usr/bin/env bash
# Tests d'intégration du backend contre un PostgreSQL réel, à lancer sur machine de test.
# Une base jetable par exécution : réseau et conteneur nommés au hasard, détruits à la sortie,
# pour que deux exécutions concurrentes ne se détruisent jamais mutuellement.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="miles-it-$(date +%s)-$$"
PG_PASSWORD="$(openssl rand -hex 16)"

command -v docker >/dev/null || { echo "docker introuvable : voir https://docs.docker.com/engine/install/" >&2; exit 1; }

cleanup() {
  docker rm -f "$RUN_ID-db" >/dev/null 2>&1 || true
  docker network rm "$RUN_ID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create "$RUN_ID" >/dev/null
docker run -d --name "$RUN_ID-db" --network "$RUN_ID" \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" postgres:16 >/dev/null

for _ in $(seq 1 60); do
  docker exec "$RUN_ID-db" pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$RUN_ID-db" pg_isready -U postgres >/dev/null \
  || { echo "PostgreSQL jetable jamais prêt (docker logs $RUN_ID-db)" >&2; exit 1; }

docker build -q --target test -t "$RUN_ID-backend" "$REPO_DIR/backend" >/dev/null
docker run --rm --network "$RUN_ID" \
  -e MILES_TEST_DATABASE_URL="postgresql://postgres:$PG_PASSWORD@$RUN_ID-db:5432/postgres" \
  "$RUN_ID-backend" -m integration -v "$@"
docker image rm "$RUN_ID-backend" >/dev/null 2>&1 || true
