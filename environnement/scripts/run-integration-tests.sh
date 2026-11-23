#!/usr/bin/env bash
# Tests d'intégration du module d'environnement, à lancer sur machine de test :
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
RUN_ID="environnement-it-$(date +%s)-$$"
PG_PASSWORD="$(openssl rand -hex 16)"
RUNTIME_UID=10001
# Fournisseur OIDC jetable : le parcours de connexion s'éprouve contre un vrai serveur
# (découverte, PKCE, jetons signés), pas contre une doublure écrite par nous.
OIDC_IMAGE="ghcr.io/navikt/mock-oauth2-server:2.1.10"
OIDC_CONFIG='{"interactiveLogin":false,"tokenCallbacks":[{"issuerId":"miles","requestMappings":[{"requestParam":"code","match":"*","claims":{"sub":"alice-sub","name":"Alice","email":"alice@example.org","aud":["miles-client"]}}]}]}'
MOUNT_DIR="$(mktemp -d)"

# Ce que la campagne va éprouver, AVANT tout le reste : c'est la première ligne du journal,
# et c'est ce qui manquait le 22/11/2026 (bug `18b6f722`). Le dépôt, pas le produit : c'est
# `HEAD` qui décide de ce qui est éprouvé, pas le répertoire d'où l'on part.
socle_it_source_eprouvee "$PRODUIT_DIR/.."

socle_it_docker_present

cleanup() {
  # Le code de sortie se capture en PREMIER : tout ce qui suit l'écraserait, et c'est lui
  # que le verdict final annonce.
  local code=$?
  # Conteneurs (par étiquette) puis réseau : la garde du socle porte la panne du 22/11/2026.
  socle_it_ressources_jetables_retirees "$RUN_ID"
  docker image rm "$RUN_ID-backend" >/dev/null 2>&1 || true
  rm -rf "$MOUNT_DIR"
  socle_it_verdict_final "$code"
}
trap cleanup EXIT

docker network create "$RUN_ID" >/dev/null
docker run -d --name "$RUN_ID-db" --label "miles-campagne=$RUN_ID" --network "$RUN_ID" \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" postgres:16 >/dev/null

socle_it_postgres_pret "$RUN_ID-db"

docker run -d --name "$RUN_ID-oidc" --label "miles-campagne=$RUN_ID" --network "$RUN_ID" -e JSON_CONFIG="$OIDC_CONFIG" \
  "$OIDC_IMAGE" >/dev/null

# --build-context socle=… : même mécanisme que le compose du produit. Sans lui, le
# verrou référence un paquet absent du contexte et la construction échoue sur la
# résolution, pas sur le code.
# Une campagne bâtit des images : même garde que le déploiement, même plancher.
# Posée ICI et non dans `integration.sh` : la garde se partage, la SÉQUENCE reste au
# produit (décision du 28/10/2026). Mesure du 11/11/2026 : les campagnes de la
# journée ont porté le disque de la machine de test de 75 % à 87 % — la garde du
# matin ne couvrait que `dev-deploy.sh`, et une garde qui protège une moitié des
# bâtisseurs protège mal.
socle_espace_avant_construction "${ESPACE_MINIMUM_MO:-4096}"
docker build -q --target test -t "$RUN_ID-backend" \
  --build-context "socle=$PRODUIT_DIR/../socle/python" "$PRODUIT_DIR/backend" >/dev/null

# Le fournisseur démarre en quelques secondes : on attend sa découverte, depuis le réseau.
oidc_ready=0
for essai in $(seq 1 60); do
  # Le nom porte le NUMÉRO D'ESSAI : un `--rm` qui vient de sortir peut retenir son nom
  # une fraction de seconde, et réutiliser le même nom soixante fois de suite changerait
  # une sonde de disponibilité en conflit de nom.
  if docker run --rm --name "$RUN_ID-sonde-oidc-$essai" --label "miles-campagne=$RUN_ID" \
      --network "$RUN_ID" --entrypoint /opt/venv/bin/python "$RUN_ID-backend" \
      -c "import httpx,sys; sys.exit(httpx.get('http://$RUN_ID-oidc:8080/miles/.well-known/openid-configuration').status_code != 200)" \
      >/dev/null 2>&1; then
    oidc_ready=1
    break
  fi
  sleep 1
done
[[ "$oidc_ready" == 1 ]] || { echo "fournisseur OIDC jetable jamais prêt (docker logs $RUN_ID-oidc)" >&2; exit 1; }

echo "==> [1/2] tests contre PostgreSQL et un vrai fournisseur OIDC"
docker run --rm --name "$RUN_ID-pytest-pg" --label "miles-campagne=$RUN_ID" --network "$RUN_ID" \
  -e MILES_TEST_DATABASE_URL="postgresql://postgres:$PG_PASSWORD@$RUN_ID-db:5432/postgres" \
  -e MILES_TEST_OIDC_URL="http://$RUN_ID-oidc:8080" \
  "$RUN_ID-backend" -m integration -v --ignore=tests/integration/test_env_mount.py "$@"

echo "==> [2/2] écriture du compte d'amorçage à travers des fichiers montés un par un"
original="MILES_DB_PASSWORD=ne-pas-toucher
MILES_HTTP_PORT=8182"
printf '%s\n' "$original" > "$MOUNT_DIR/.env"
: > "$MOUNT_DIR/.env.bak"
chmod 600 "$MOUNT_DIR/.env" "$MOUNT_DIR/.env.bak"
chown "$RUNTIME_UID:$RUNTIME_UID" "$MOUNT_DIR/.env" "$MOUNT_DIR/.env.bak"
# pytest du venv directement : `uv run` voudrait écrire dans le venv, ce que
# l'utilisateur du runtime ne peut pas faire.
docker run --rm --name "$RUN_ID-pytest-env" --label "miles-campagne=$RUN_ID" \
  --user "$RUNTIME_UID:$RUNTIME_UID" \
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

# Dernière ligne de la séquence, et c'est tout ce qu'elle veut dire : les étapes ci-dessus
# ont toutes passé (`set -e` aurait sorti avant). C'est ce que le verdict de sortie lit pour
# distinguer un succès d'une campagne tuée en chemin.
socle_it_campagne_achevee
