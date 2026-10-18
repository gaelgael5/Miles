#!/usr/bin/env bash
# Livraison de Miles sur machine de test : seule voie de déploiement (voir CLAUDE.md et
# la skill test-machine-deployment). Chaque garde vient d'une panne réelle — n'en retire
# aucune sans avoir lu celle qui l'a motivée.
#
#   ./dev-deploy.sh                       déploiement normal (idempotent, rejouable)
#   MILES_HTTP_PORT=8180 ./dev-deploy.sh  premier passage sur un port autre que 8080
#   ./dev-deploy.sh --no-nohup            sans filet de session (CI, débogage pas à pas)
#   ./dev-deploy.sh --bootstrap-deploy-key [--force]   clé de déploiement SSH (dépôt privé)
#   ./dev-deploy.sh --reset-db            DÉTRUIT la base (confirmation exigée), puis s'arrête
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="dev"
STATE_DIR="$REPO_DIR/.deploy"
LOG_FILE="$STATE_DIR/deploy-$(date +%Y%m%d-%H%M%S).log"
PURGE_STAMP="$STATE_DIR/last-purge"
ENV_FILE="$REPO_DIR/.env"
DEPLOY_KEY="$HOME/.ssh/miles_deploy_key"
TOTAL_STEPS=9
CONTAINER_WAIT_S=90
HEALTH_WAIT_S=120
PURGE_EVERY_S=$((7 * 24 * 3600))

NO_NOHUP=0 BOOTSTRAP_KEY=0 FORCE=0 RESET_DB=0
for arg in "$@"; do
  case "$arg" in
    --no-nohup) NO_NOHUP=1 ;;
    --bootstrap-deploy-key) BOOTSTRAP_KEY=1 ;;
    --force) FORCE=1 ;;
    --reset-db) RESET_DB=1 ;;
    *) echo "option inconnue : $arg" >&2; exit 2 ;;
  esac
done

step() { echo "==> [$1/$TOTAL_STEPS] $2"; }
fail() { echo "ÉCHEC : $*" >&2; exit 1; }
compose() { docker compose --project-directory "$REPO_DIR" --env-file "$ENV_FILE" "$@"; }

# --- 0. Survivre à la perte de la session -----------------------------------------------
# Le script arrête la stack ; lancé depuis une session qu'elle héberge (ou une connexion
# mobile qui tombe), le SIGHUP le tuerait entre l'arrêt et le redémarrage.
mkdir -p "$STATE_DIR"
if [[ "$NO_NOHUP" -eq 0 && -z "${MILES_DEPLOY_LOGGING:-}" ]]; then
  trap '' HUP
  export MILES_DEPLOY_LOGGING=1
  exec > >(tee -a "$LOG_FILE") 2>&1
  echo "journal : $LOG_FILE"
fi

# --- Mode bootstrap : clé de déploiement générée SUR l'hôte ------------------------------
if [[ "$BOOTSTRAP_KEY" -eq 1 && -z "${MILES_DEPLOY_REEXEC:-}" ]]; then
  # La clé privée ne quitte jamais l'hôte : seule la publique est affichée, en dernier.
  if [[ -f "$DEPLOY_KEY" && "$FORCE" -eq 0 ]]; then
    echo "clé existante conservée (--force pour régénérer)."
  else
    rm -f "$DEPLOY_KEY" "$DEPLOY_KEY.pub"
    ssh-keygen -q -t ed25519 -N "" -C "miles-deploy@$(hostname)" -f "$DEPLOY_KEY"
  fi
  if ! grep -q "miles_deploy_key" "$HOME/.ssh/config" 2>/dev/null; then
    printf '\nHost github.com\n  IdentityFile %s\n  IdentitiesOnly yes\n' "$DEPLOY_KEY" \
      >> "$HOME/.ssh/config"
  fi
  echo "Enregistrer cette clé dans GitHub > Settings > Deploy keys (lecture seule) :"
  cat "$DEPLOY_KEY.pub"
  read -r -p "Appuyer sur Entrée une fois la clé enregistrée pour poursuivre le déploiement… " _
fi

# --- 1. Prérequis ----------------------------------------------------------------------
step 1 "prérequis"
command -v git >/dev/null || fail "git absent : sudo apt-get install -y git"
command -v docker >/dev/null || fail "docker absent : https://docs.docker.com/engine/install/debian/"
docker compose version >/dev/null 2>&1 \
  || fail "plugin compose absent : sudo apt-get install -y docker-compose-plugin"
command -v curl >/dev/null || fail "curl absent : sudo apt-get install -y curl"
command -v openssl >/dev/null || fail "openssl absent : sudo apt-get install -y openssl"
docker info >/dev/null 2>&1 || fail "démon docker injoignable : sudo usermod -aG docker \$USER, puis se reconnecter"

# --- 2. Mise à jour depuis le dépôt, puis ré-exécution ---------------------------------
step 2 "mise à jour depuis origin/$BRANCH"
# Pas de mode « déploie ce qui est là » : sans réseau ni accès au dépôt, on échoue.
git -C "$REPO_DIR" fetch origin "$BRANCH" \
  || fail "récupération impossible (accès au dépôt ? dépôt privé : --bootstrap-deploy-key)"
[[ "$(git -C "$REPO_DIR" branch --show-current)" == "$BRANCH" ]] \
  || fail "la copie n'est pas sur $BRANCH : git -C $REPO_DIR checkout $BRANCH"
before="$(git -C "$REPO_DIR" rev-parse HEAD)"
git -C "$REPO_DIR" merge --ff-only "origin/$BRANCH" \
  || fail "copie locale divergente d'origin/$BRANCH : aucune retouche locale n'est admise ici"
if [[ "$before" != "$(git -C "$REPO_DIR" rev-parse HEAD)" && -z "${MILES_DEPLOY_REEXEC:-}" ]]; then
  # Le code a changé : on se relance dans la version récupérée, sinon un script, un compose
  # ou un Dockerfile périmés déploieraient le code neuf.
  echo "nouvelle version récupérée, ré-exécution du script à jour"
  MILES_DEPLOY_REEXEC=1 exec "$REPO_DIR/dev-deploy.sh" "$@"
fi

# --- 3 & 4. État et configuration, sans rien écraser -----------------------------------
step 3 "configuration (.env)"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
# Un mot de passe régénéré à chaque passage casserait la base déjà initialisée avec l'ancien.
if ! grep -q '^MILES_DB_PASSWORD=.\+' "$ENV_FILE"; then
  sed -i '/^MILES_DB_PASSWORD=/d' "$ENV_FILE"
  echo "MILES_DB_PASSWORD=$(openssl rand -hex 24)" >> "$ENV_FILE"
  echo "mot de passe de base généré (première exécution)"
fi
# Machines de test partagées : 8080 y est souvent pris. Le port se choisit au premier passage
# (MILES_HTTP_PORT=… ./dev-deploy.sh), puis .env fait foi — l'environnement ne le change plus.
if ! grep -q '^MILES_HTTP_PORT=' "$ENV_FILE"; then
  echo "MILES_HTTP_PORT=${MILES_HTTP_PORT:-8080}" >> "$ENV_FILE"
fi
HTTP_PORT="$(grep '^MILES_HTTP_PORT=' "$ENV_FILE" | tail -1 | cut -d= -f2)"
[[ "$HTTP_PORT" =~ ^[0-9]{2,5}$ ]] || fail "MILES_HTTP_PORT invalide dans .env : $HTTP_PORT"

# --- 11. Mode destructif isolé : drapeau explicite, confirmation, court-circuit ---------
if [[ "$RESET_DB" -eq 1 ]]; then
  read -r -p "Taper « detruire miles » pour supprimer définitivement la base : " answer
  [[ "$answer" == "detruire miles" ]] || fail "confirmation refusée, rien n'a été touché"
  compose down --volumes --remove-orphans
  echo "base détruite ; relancer ./dev-deploy.sh pour redéployer."
  exit 0
fi

# --- 5. Construire, arrêter, relancer -------------------------------------------------
step 4 "construction des images depuis la copie du dépôt"
# Jamais sautée : c'est ici, sur copie fraîche, qu'on prouve que les images se bâtissent.
compose build --pull || fail "construction en échec : défaut du dépôt, à corriger d'abord"

step 5 "arrêt de la stack (orphelins compris)"
compose down --remove-orphans

# --- 6. Conflit de port, APRÈS l'arrêt ------------------------------------------------
# Sondé avant l'arrêt, le port serait pris… par notre propre service.
if (exec 3<>"/dev/tcp/127.0.0.1/$HTTP_PORT") 2>/dev/null; then
  fail "port $HTTP_PORT occupé par un autre service (ss -ltnp 'sport = :$HTTP_PORT')"
fi
compose up -d

# --- 7. Attendre un conteneur réellement exécutable avant de migrer ---------------------
step 6 "attente du conteneur backend"
stable=0
for _ in $(seq 1 "$CONTAINER_WAIT_S"); do
  state="$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' "$(compose ps -q backend)" 2>/dev/null || true)"
  if [[ "$state" == "running "* ]]; then stable=$((stable + 1)); else stable=0; fi
  # Trois secondes consécutives en marche : un conteneur qui redémarre en boucle ne passe pas.
  [[ "$stable" -ge 3 ]] && break
  sleep 1
done
[[ "$stable" -ge 3 ]] || fail "backend jamais stable : docker compose logs backend"

step 7 "migrations"
compose exec -T backend miles-migrate apply || fail "migration en échec : docker compose logs backend"

# --- 8. Le schéma est-il réellement à jour ? -------------------------------------------
step 8 "vérification de la version de schéma"
# « apply » peut sortir en succès sans avoir atteint la dernière version (base tamponnée
# à la main) : on interroge le résultat, pas le code de retour.
compose exec -T backend miles-migrate status || fail "schéma en retard après migration"

# --- 9. Contrôle de santé final, plafonné ----------------------------------------------
step 9 "contrôle de santé sur le port publié $HTTP_PORT"
# Par le frontend nginx, sur le port réellement exposé : valide aussi le proxy /api.
healthy=0
for _ in $(seq 1 "$HEALTH_WAIT_S"); do
  if curl -fsS "http://127.0.0.1:$HTTP_PORT/api/health" >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done
[[ "$healthy" -eq 1 ]] || fail "santé KO après ${HEALTH_WAIT_S}s : curl -s http://127.0.0.1:$HTTP_PORT/api/health"
echo "déploiement OK : $(git -C "$REPO_DIR" rev-parse --short HEAD) sur http://$(hostname):$HTTP_PORT"

# --- 10. Récupération d'espace disque, au plus une fois par semaine --------------------
# Après la santé (ne retarde pas la mise à disposition), cache et images détaggées
# seulement (jamais les volumes), et jamais un motif d'échec du déploiement.
now="$(date +%s)"
last="$(cat "$PURGE_STAMP" 2>/dev/null || echo 0)"
if (( now - last > PURGE_EVERY_S )); then
  {
    before_kb="$(df -k --output=avail /var/lib/docker 2>/dev/null | tail -1 || echo 0)"
    docker builder prune -f >/dev/null && docker image prune -f >/dev/null
    after_kb="$(df -k --output=avail /var/lib/docker 2>/dev/null | tail -1 || echo 0)"
    echo "purge hebdomadaire : $(( (after_kb - before_kb) / 1024 )) Mo récupérés"
    echo "$now" > "$PURGE_STAMP"
  } || echo "purge en échec (sans effet sur le déploiement)"
fi
