#!/usr/bin/env bash
# Tests d'intégration du module d'enrôlement, à lancer sur machine de test :
#   1. contre un PostgreSQL réel et un fournisseur OIDC réel (jetables) ;
#   2. écriture du compte d'amorçage à travers .env et .env.bak montés FICHIER PAR
#      FICHIER, avec l'utilisateur non root du runtime, comme dans docker-compose.yml.
# Ressources jetables par exécution : réseau, conteneurs et dossier nommés au hasard,
# détruits à la sortie, pour que deux exécutions concurrentes ne se détruisent jamais.
set -euo pipefail

# Les GARDES de campagne viennent du socle, la SÉQUENCE reste ici (décision de Gael du
# 28/10/2026) : les ressources jetables et les invocations de pytest sont propres à ce
# produit, la disponibilité d'un PostgreSQL jetable ne l'est pas.
# shellcheck source=../../socle/deploy/integration.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../socle/deploy" && pwd)/integration.sh"

# Le répertoire du PRODUIT, pas du dépôt : le dépôt en porte trois.
PRODUIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="enrolement-it-$(date +%s)-$$"
PG_PASSWORD="$(openssl rand -hex 16)"
RUNTIME_UID=10001
# Fournisseur OIDC jetable : le parcours de connexion s'éprouve contre un vrai serveur
# (découverte, PKCE, jetons signés), pas contre une doublure écrite par nous.
OIDC_IMAGE="ghcr.io/navikt/mock-oauth2-server:2.1.10"
OIDC_CONFIG='{"interactiveLogin":false,"tokenCallbacks":[{"issuerId":"miles","requestMappings":[{"requestParam":"code","match":"*","claims":{"sub":"alice-sub","name":"Alice","email":"alice@example.org","aud":["miles-client"]}}]}]}'
MOUNT_DIR="$(mktemp -d)"

socle_it_docker_present

cleanup() {
  docker rm -f "$RUN_ID-db" "$RUN_ID-oidc" >/dev/null 2>&1 || true
  docker network rm "$RUN_ID" >/dev/null 2>&1 || true
  docker image rm "$RUN_ID-backend" >/dev/null 2>&1 || true
  rm -rf "$MOUNT_DIR"
}
trap cleanup EXIT

docker network create "$RUN_ID" >/dev/null
docker run -d --name "$RUN_ID-db" --network "$RUN_ID" \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" postgres:16 >/dev/null

socle_it_postgres_pret "$RUN_ID-db"

docker run -d --name "$RUN_ID-oidc" --network "$RUN_ID" -e JSON_CONFIG="$OIDC_CONFIG" \
  "$OIDC_IMAGE" >/dev/null

# --build-context socle=… : même mécanisme que le compose du produit. Sans lui, le
# verrou référence un paquet absent du contexte et la construction échoue sur la
# résolution, pas sur le code.
docker build -q --target test -t "$RUN_ID-backend" \
  --build-context "socle=$PRODUIT_DIR/../socle/python" "$PRODUIT_DIR/backend" >/dev/null

# Le fournisseur démarre en quelques secondes : on attend sa découverte, depuis le réseau.
oidc_ready=0
for _ in $(seq 1 60); do
  if docker run --rm --network "$RUN_ID" --entrypoint /opt/venv/bin/python "$RUN_ID-backend" \
      -c "import httpx,sys; sys.exit(httpx.get('http://$RUN_ID-oidc:8080/miles/.well-known/openid-configuration').status_code != 200)" \
      >/dev/null 2>&1; then
    oidc_ready=1
    break
  fi
  sleep 1
done
[[ "$oidc_ready" == 1 ]] || { echo "fournisseur OIDC jetable jamais prêt (docker logs $RUN_ID-oidc)" >&2; exit 1; }

echo "==> [1/2] tests contre PostgreSQL et un vrai fournisseur OIDC"
docker run --rm --network "$RUN_ID" \
  -e MILES_TEST_DATABASE_URL="postgresql://postgres:$PG_PASSWORD@$RUN_ID-db:5432/postgres" \
  -e MILES_TEST_OIDC_URL="http://$RUN_ID-oidc:8080" \
  "$RUN_ID-backend" -m integration -v --ignore=tests/integration/test_env_mount.py "$@"

echo "==> [2/2] écriture du compte d'amorçage à travers des fichiers montés un par un"
original="MILES_DB_PASSWORD=ne-pas-toucher
MILES_HTTP_PORT=8181"
printf '%s\n' "$original" > "$MOUNT_DIR/.env"
: > "$MOUNT_DIR/.env.bak"
chmod 600 "$MOUNT_DIR/.env" "$MOUNT_DIR/.env.bak"
chown "$RUNTIME_UID:$RUNTIME_UID" "$MOUNT_DIR/.env" "$MOUNT_DIR/.env.bak"
# pytest du venv directement : `uv run` voudrait écrire dans le venv, ce que
# l'utilisateur du runtime ne peut pas faire.
docker run --rm --user "$RUNTIME_UID:$RUNTIME_UID" \
  -v "$MOUNT_DIR/.env:/run/miles/.env" -v "$MOUNT_DIR/.env.bak:/run/miles/.env.bak" \
  -e MILES_TEST_MOUNTED_ENV=/run/miles/.env -e MILES_TEST_MOUNTED_BAK=/run/miles/.env.bak \
  --entrypoint /opt/venv/bin/pytest "$RUN_ID-backend" \
  -m integration -v -p no:cacheprovider tests/integration/test_env_mount.py

# Ce qui compte est ce que l'HÔTE voit, pas ce que le conteneur croit avoir écrit.
fail() { echo "ÉCHEC montage : $*" >&2; exit 1; }
[[ "$(head -2 "$MOUNT_DIR/.env")" == "$original" ]] || fail "entrées existantes modifiées"
grep -q "^MILES_ADMIN_USERNAME='admin'$" "$MOUNT_DIR/.env" || fail "compte absent de .env côté hôte"
# shellcheck disable=SC2016  # $ littéraux de l'empreinte, pas une expansion
grep -q '^MILES_ADMIN_PASSWORD_HASH=.\$argon2id\$' "$MOUNT_DIR/.env" || fail "empreinte absente côté hôte"
[[ "$(cat "$MOUNT_DIR/.env.bak")" == "$original" ]] || fail ".env.bak ne contient pas l'original"
[[ "$(stat -c %a "$MOUNT_DIR/.env")" == 600 ]] || fail "droits de .env modifiés"
echo "montage fichier par fichier : écriture vérifiée côté hôte"
