#!/usr/bin/env bash
# Tests d'intégration du backend, à lancer sur machine de test :
#   1. contre un PostgreSQL réel ;
#   2. écriture du compte d'amorçage à travers .env et .env.bak montés FICHIER PAR
#      FICHIER, avec l'utilisateur non root du runtime, comme dans docker-compose.yml ;
#   3. request/response MQTT 5 contre un vrai Mosquitto, configuré par mosquitto/ du dépôt.
# Ressources jetables par exécution : réseau, conteneur et dossier nommés au hasard,
# détruits à la sortie, pour que deux exécutions concurrentes ne se détruisent jamais.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="miles-it-$(date +%s)-$$"
PG_PASSWORD="$(openssl rand -hex 16)"
RUNTIME_UID=10001
MOSQUITTO_IMAGE="eclipse-mosquitto:2.0.20"
MOSQUITTO_UID=1883
MOUNT_DIR="$(mktemp -d)"

command -v docker >/dev/null || { echo "docker introuvable : voir https://docs.docker.com/engine/install/" >&2; exit 1; }

cleanup() {
  docker rm -f "$RUN_ID-db" "$RUN_ID-mqtt" >/dev/null 2>&1 || true
  docker network rm "$RUN_ID" >/dev/null 2>&1 || true
  docker image rm "$RUN_ID-backend" >/dev/null 2>&1 || true
  rm -rf "$MOUNT_DIR"
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

echo "==> [1/3] tests contre PostgreSQL"
docker run --rm --network "$RUN_ID" \
  -e MILES_TEST_DATABASE_URL="postgresql://postgres:$PG_PASSWORD@$RUN_ID-db:5432/postgres" \
  "$RUN_ID-backend" -m integration -v --ignore=tests/integration/test_env_mount.py \
  --ignore=tests/integration/test_mqtt_broker.py "$@"

echo "==> [2/3] écriture du compte d'amorçage à travers des fichiers montés un par un"
original="MILES_DB_PASSWORD=ne-pas-toucher
MILES_HTTP_PORT=8180"
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

echo "==> [3/3] request/response MQTT 5 contre Mosquitto"
MQTT_DIR="$MOUNT_DIR/mosquitto"
mkdir -p "$MQTT_DIR"
cp "$REPO_DIR/mosquitto/mosquitto.conf" "$REPO_DIR/mosquitto/acl" "$MQTT_DIR/"
declare -A MQTT_PASSWORDS
: > "$MQTT_DIR/passwd"
for user in miles-backend term-42 term-43; do
  MQTT_PASSWORDS[$user]="$(openssl rand -hex 16)"
  printf '%s:%s\n' "$user" "${MQTT_PASSWORDS[$user]}" >> "$MQTT_DIR/passwd"
done
# -U hache en place le fichier en clair : aucun mot de passe en argument (`ps`).
docker run --rm -v "$MQTT_DIR/passwd:/p" "$MOSQUITTO_IMAGE" mosquitto_passwd -U /p
chmod 600 "$MQTT_DIR/passwd" "$MQTT_DIR/acl"
chown "$MOSQUITTO_UID:$MOSQUITTO_UID" "$MQTT_DIR/passwd" "$MQTT_DIR/acl"
docker run -d --name "$RUN_ID-mqtt" --network "$RUN_ID" \
  -v "$MQTT_DIR/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
  -v "$MQTT_DIR/passwd:/mosquitto/config/passwd:ro" \
  -v "$MQTT_DIR/acl:/mosquitto/config/acl:ro" \
  "$MOSQUITTO_IMAGE" >/dev/null
sleep 2
docker run --rm --network "$RUN_ID" \
  -e MILES_TEST_MQTT_HOST="$RUN_ID-mqtt" \
  -e MILES_TEST_MQTT_PASSWORD_MILES_BACKEND="${MQTT_PASSWORDS[miles-backend]}" \
  -e MILES_TEST_MQTT_PASSWORD_TERM_42="${MQTT_PASSWORDS[term-42]}" \
  -e MILES_TEST_MQTT_PASSWORD_TERM_43="${MQTT_PASSWORDS[term-43]}" \
  "$RUN_ID-backend" -m integration -v tests/integration/test_mqtt_broker.py \
  || { docker logs "$RUN_ID-mqtt" | tail -20 >&2; exit 1; }
