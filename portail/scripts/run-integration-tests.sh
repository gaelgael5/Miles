#!/usr/bin/env bash
# Tests d'intégration du backend, à lancer sur machine de test :
#   1. contre un PostgreSQL réel ;
#   2. écriture du compte d'amorçage à travers .env et .env.bak montés FICHIER PAR
#      FICHIER, avec l'utilisateur non root du runtime, comme dans docker-compose.yml ;
#   3. request/response MQTT 5 contre un vrai Mosquitto, configuré par mosquitto/ du dépôt.
# Ressources jetables par exécution : réseau, conteneur et dossier nommés au hasard,
# détruits à la sortie, pour que deux exécutions concurrentes ne se détruisent jamais.
set -euo pipefail

# Le répertoire du PRODUIT, pas du dépôt : depuis le 27/10/2026 le dépôt en porte trois.
PRODUIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_ID="miles-it-$(date +%s)-$$"
PG_PASSWORD="$(openssl rand -hex 16)"
RUNTIME_UID=10001
MOSQUITTO_IMAGE="eclipse-mosquitto:2.0.20"
# Fournisseur OIDC jetable : le parcours de connexion s'éprouve contre un vrai serveur
# (découverte, PKCE, jetons signés), pas contre une doublure écrite par nous.
OIDC_IMAGE="ghcr.io/navikt/mock-oauth2-server:2.1.10"
KEYCLOAK_IMAGE="quay.io/keycloak/keycloak:26.0.7"
# Forge git jetable : les cinq droits du workspace s'éprouvent par de vrais push.
GITEA_IMAGE="gitea/gitea:1.22.6"
KEYCLOAK_SECRET="$(openssl rand -hex 16)"
OIDC_CONFIG='{"interactiveLogin":false,"tokenCallbacks":[{"issuerId":"miles","requestMappings":[{"requestParam":"code","match":"*","claims":{"sub":"alice-sub","name":"Alice","email":"alice@example.org","aud":["miles-client"]}}]}]}'
MOSQUITTO_UID=1883
MOUNT_DIR="$(mktemp -d)"

command -v docker >/dev/null || { echo "docker introuvable : voir https://docs.docker.com/engine/install/" >&2; exit 1; }

cleanup() {
  docker rm -f "$RUN_ID-db" "$RUN_ID-mqtt" "$RUN_ID-oidc" "$RUN_ID-kc" "$RUN_ID-gitea" >/dev/null 2>&1 || true
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

docker run -d --name "$RUN_ID-oidc" --network "$RUN_ID" -e JSON_CONFIG="$OIDC_CONFIG" \
  "$OIDC_IMAGE" >/dev/null

# Keycloak jetable, realm importé : la vérification du service de sécurité s'éprouve
# contre le vrai serveur, dont les réponses (404 de realm, 401 de client) font foi.
KC_DIR="$MOUNT_DIR/keycloak"
mkdir -p "$KC_DIR"
printf '{"realm":"miles","enabled":true,"clients":[{"clientId":"miles-backoffice","enabled":true,"publicClient":false,"secret":"%s","serviceAccountsEnabled":true,"standardFlowEnabled":false}]}' \
  "$KEYCLOAK_SECRET" > "$KC_DIR/miles-realm.json"
# Le processus Keycloak ne tourne pas en root : le dossier monté doit lui être lisible.
chmod 755 "$MOUNT_DIR" "$KC_DIR"
chmod 644 "$KC_DIR/miles-realm.json"
docker run -d --name "$RUN_ID-kc" --network "$RUN_ID" -v "$KC_DIR:/opt/keycloak/data/import:ro" \
  -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD="$(openssl rand -hex 12)" \
  "$KEYCLOAK_IMAGE" start-dev --import-realm >/dev/null

docker run -d --name "$RUN_ID-gitea" --network "$RUN_ID" \
  -e GITEA__security__INSTALL_LOCK=true -e GITEA__database__DB_TYPE=sqlite3 \
  -e GITEA__server__ROOT_URL="http://$RUN_ID-gitea:3000/" "$GITEA_IMAGE" >/dev/null

docker build -q --target test -t "$RUN_ID-backend" "$PRODUIT_DIR/backend" >/dev/null

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
kc_ready=0
for _ in $(seq 1 120); do
  if docker run --rm --network "$RUN_ID" --entrypoint /opt/venv/bin/python "$RUN_ID-backend" \
      -c "import httpx,sys; sys.exit(httpx.get('http://$RUN_ID-kc:8080/realms/miles/.well-known/openid-configuration').status_code != 200)" \
      >/dev/null 2>&1; then
    kc_ready=1
    break
  fi
  sleep 2
done
[[ "$kc_ready" == 1 ]] || { echo "Keycloak jetable jamais prêt (docker logs $RUN_ID-kc)" >&2; exit 1; }
gitea_ready=0
for _ in $(seq 1 60); do
  if docker exec "$RUN_ID-gitea" curl -sf http://localhost:3000/api/v1/version >/dev/null 2>&1; then
    gitea_ready=1
    break
  fi
  sleep 1
done
[[ "$gitea_ready" == 1 ]] || { echo "Gitea jetable jamais prêt (docker logs $RUN_ID-gitea)" >&2; exit 1; }
# Mot de passe jamais en argument : gitea admin le reçoit par l'option, mais dans le
# conteneur jetable seulement, détruit à la sortie. Les jetons, eux, restent en mémoire.
docker exec -u git "$RUN_ID-gitea" gitea admin user create --username miles --admin \
  --password "$(openssl rand -hex 16)" --email miles@forge.invalid --must-change-password=false >/dev/null
GITEA_TOKEN="$(docker exec -u git "$RUN_ID-gitea" gitea admin user generate-access-token \
  --username miles --token-name ecriture --scopes write:repository,write:user --raw | tail -1)"
GITEA_READ_TOKEN="$(docker exec -u git "$RUN_ID-gitea" gitea admin user generate-access-token \
  --username miles --token-name lecture --scopes read:repository --raw | tail -1)"

echo "==> [1/3] tests contre PostgreSQL"
docker run --rm --network "$RUN_ID" \
  -e MILES_TEST_DATABASE_URL="postgresql://postgres:$PG_PASSWORD@$RUN_ID-db:5432/postgres" \
  -e MILES_TEST_OIDC_URL="http://$RUN_ID-oidc:8080" \
  -e MILES_TEST_KEYCLOAK_URL="http://$RUN_ID-kc:8080" -e MILES_TEST_KEYCLOAK_SECRET="$KEYCLOAK_SECRET" \
  -e MILES_TEST_GITEA_URL="http://$RUN_ID-gitea:3000" -e MILES_TEST_GITEA_TOKEN="$GITEA_TOKEN" \
  -e MILES_TEST_GITEA_READ_TOKEN="$GITEA_READ_TOKEN" \
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
cp "$PRODUIT_DIR/mosquitto/mosquitto.conf" "$PRODUIT_DIR/mosquitto/acl" "$MQTT_DIR/"
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
