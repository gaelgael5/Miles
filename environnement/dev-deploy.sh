#!/usr/bin/env bash
# Livraison du module d'environnement sur machine de test : seule voie de déploiement (voir
# CLAUDE.md et la skill test-machine-deployment). Chaque garde vient d'une panne réelle —
# n'en retire aucune sans avoir lu celle qui l'a motivée.
#
#   ./dev-deploy.sh                       déploiement normal (idempotent, rejouable)
#   MILES_HTTP_PORT=8182 ./dev-deploy.sh  premier passage sur un port autre que 8082
#   ./dev-deploy.sh --no-nohup            sans filet de session (CI, débogage pas à pas)
#   ./dev-deploy.sh --bootstrap-deploy-key [--force]   clé de déploiement SSH (dépôt privé)
#   ./dev-deploy.sh --reset-db            DÉTRUIT la base (confirmation exigée), puis s'arrête
#
# Annuaire du portail : EXPOSE_PORTAL_URL et EXPOSE_WORKSPACE (EXPOSE_HOST facultatif) se
# donnent au premier passage, puis sont figés dans .env. PORTAL_TOKEN = code TOTP
# « login:code » (outil MCP totp_code), fourni à CHAQUE passage, jamais écrit nulle part.
set -euo pipefail

# Le dépôt porte trois produits ; chacun a son répertoire, sa stack et son dev-deploy.sh.
# Ce script ne connaît que LE SIEN — d'où le nom de la variable.
PRODUIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPOT_DIR="$(cd "$PRODUIT_DIR/.." && pwd)"
BRANCH="dev"
STATE_DIR="$PRODUIT_DIR/.deploy"
LOG_FILE="$STATE_DIR/deploy-$(date +%Y%m%d-%H%M%S).log"
PURGE_STAMP="$STATE_DIR/last-purge"
ENV_FILE="$PRODUIT_DIR/.env"
BACKUP_ENV_FILE="$PRODUIT_DIR/.env.bak"
ADMIN_PASSWORD_FILE="$STATE_DIR/admin-password"
# uid de l'utilisateur non root de l'image backend (backend/Dockerfile).
RUNTIME_UID=10001
DEPLOY_KEY="$HOME/.ssh/miles_deploy_key"
TOTAL_STEPS=10
# Nom publié à l'annuaire : doit rester le `name:` de docker-compose.yml, sinon le lien de
# la machine de test dans le portail ne retrouve pas la stack. Distinct de celui du
# portail, les deux stacks cohabitant sur la même machine.
SERVICE_NAME="miles-environnement"
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
compose() { docker compose --project-directory "$PRODUIT_DIR" --env-file "$ENV_FILE" "$@"; }
env_value() { grep "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }
# Valeur non secrète prise dans l'environnement au premier passage, puis figée : .env fait foi.
persist_default() {
  local key="$1" default="${2:-}"
  local value="${!key:-$default}"
  grep -q "^$key=" "$ENV_FILE" && return 0
  [[ -n "$value" ]] && echo "$key=$value" >> "$ENV_FILE"
  return 0
}

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
git -C "$DEPOT_DIR" fetch origin "$BRANCH" \
  || fail "récupération impossible (accès au dépôt ? dépôt privé : --bootstrap-deploy-key)"
[[ "$(git -C "$DEPOT_DIR" branch --show-current)" == "$BRANCH" ]] \
  || fail "la copie n'est pas sur $BRANCH : git -C $DEPOT_DIR checkout $BRANCH"
before="$(git -C "$DEPOT_DIR" rev-parse HEAD)"
git -C "$DEPOT_DIR" merge --ff-only "origin/$BRANCH" \
  || fail "copie locale divergente d'origin/$BRANCH : aucune retouche locale n'est admise ici"
if [[ "$before" != "$(git -C "$DEPOT_DIR" rev-parse HEAD)" && -z "${MILES_DEPLOY_REEXEC:-}" ]]; then
  # Le code a changé : on se relance dans la version récupérée, sinon un script, un compose
  # ou un Dockerfile périmés déploieraient le code neuf.
  echo "nouvelle version récupérée, ré-exécution du script à jour"
  MILES_DEPLOY_REEXEC=1 exec "$PRODUIT_DIR/dev-deploy.sh" "$@"
fi

# --- 3. État et configuration, sans rien écraser ---------------------------------------
step 3 "configuration (.env)"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
# Un mot de passe régénéré à chaque passage casserait la base déjà initialisée avec l'ancien.
if ! grep -q '^MILES_DB_PASSWORD=.\+' "$ENV_FILE"; then
  sed -i '/^MILES_DB_PASSWORD=/d' "$ENV_FILE"
  echo "MILES_DB_PASSWORD=$(openssl rand -hex 24)" >> "$ENV_FILE"
  echo "mot de passe de base généré (première exécution)"
fi
# Clé des secrets de l'instance : générée UNE fois, JAMAIS régénérée. La régénérer rendrait
# illisibles tous les secrets déjà chiffrés en base avec l'ancienne — dont le secret client
# de chaque connecteur OIDC et, dans ce produit-ci, LA CLÉ PRIVÉE DE SIGNATURE DU MODULE.
# Conséquence directe de la contrainte de persistance du ticket 6a0daab6 : l'identité de
# l'environnement doit survivre au redéploiement de sa stack. La perdre casserait
# l'appariement et imposerait de réapparier à la main, puis de réaffecter les devices.
if ! grep -q '^MILES_SECRETS_KEY=.\+' "$ENV_FILE"; then
  sed -i '/^MILES_SECRETS_KEY=/d' "$ENV_FILE"
  echo "MILES_SECRETS_KEY=$(openssl rand -base64 32 | tr '+/' '-_')" >> "$ENV_FILE"
  echo "clé des secrets générée (première exécution)"
fi
# Machines de test partagées : le portail occupe souvent 8080 et le module d'enrôlement
# 8081, d'où un défaut distinct et un port choisi au premier passage.
persist_default MILES_HTTP_PORT 8082
persist_default EXPOSE_PORTAL_URL
persist_default EXPOSE_WORKSPACE
persist_default EXPOSE_HOST "$(hostname)"
HTTP_PORT="$(env_value MILES_HTTP_PORT)"
[[ "$HTTP_PORT" =~ ^[0-9]{2,5}$ ]] || fail "MILES_HTTP_PORT invalide dans .env : $HTTP_PORT"
# .env et .env.bak sont montés FICHIER PAR FICHIER dans le backend, qui y écrit le compte
# d'amorçage. Un fichier monté doit exister : absent, docker créerait un dossier à sa
# place. Ils appartiennent à l'utilisateur non root du runtime, seul à devoir y écrire ;
# root, qui lance ce script et compose, les lit de toute façon.
touch "$BACKUP_ENV_FILE"
chmod 600 "$ENV_FILE" "$BACKUP_ENV_FILE"
chown "$RUNTIME_UID:$RUNTIME_UID" "$ENV_FILE" "$BACKUP_ENV_FILE" \
  || fail "chown de .env impossible : lancer dev-deploy.sh en root (machine de test)"

# --- Mode destructif isolé : drapeau explicite, confirmation, court-circuit -------------
if [[ "$RESET_DB" -eq 1 ]]; then
  read -r -p "Taper « detruire environnement » pour supprimer définitivement la base : " answer
  [[ "$answer" == "detruire environnement" ]] || fail "confirmation refusée, rien n'a été touché"
  compose down --volumes --remove-orphans
  echo "base détruite ; relancer ./dev-deploy.sh pour redéployer."
  exit 0
fi

# --- Déclaration à l'annuaire du portail, best-effort -----------------------------------
# Faite AVANT la construction, pas après le contrôle de santé : le code TOTP vit ~30 s et
# serait périmé au bout d'un build de plusieurs minutes. La déclaration est un upsert
# idempotent ; publier une stack pas encore debout est sans effet. Rien ici ne fait
# échouer le déploiement.
declare_exposition() {
  local portal workspace host target_ip body http_code
  portal="$(env_value EXPOSE_PORTAL_URL)"
  workspace="$(env_value EXPOSE_WORKSPACE)"
  host="$(env_value EXPOSE_HOST)"
  if [[ -z "$portal" || -z "$workspace" ]]; then
    echo "annuaire non configuré (EXPOSE_PORTAL_URL / EXPOSE_WORKSPACE absents de .env) : rien à déclarer"
    return 0
  fi
  if [[ -z "${PORTAL_TOKEN:-}" ]]; then
    echo "AVERTISSEMENT : PORTAL_TOKEN absent, $workspace-$SERVICE_NAME non déclaré à l'annuaire"
    return 0
  fi
  # Seule la voie agent (/me, droits du propriétaire) est admise : un jeton d'infra admin
  # n'a rien à faire sur une machine de workspace. Le jeton n'est jamais affiché.
  if [[ ! "$PORTAL_TOKEN" =~ ^[A-Za-z0-9._@+-]+:[0-9]{6,8}$ ]]; then
    echo "AVERTISSEMENT : PORTAL_TOKEN n'a pas la forme login:code TOTP, déclaration ignorée"
    return 0
  fi
  # Ces valeurs entrent dans un JSON écrit à la main : seules des formes sûres passent.
  if [[ ! "$portal" =~ ^https?://[A-Za-z0-9.-]+(:[0-9]{2,5})?/?$ \
        || ! "$workspace" =~ ^[a-z0-9][a-z0-9-]*$ || ! "$host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
    echo "AVERTISSEMENT : EXPOSE_PORTAL_URL, EXPOSE_WORKSPACE ou EXPOSE_HOST invalide dans .env, déclaration ignorée"
    return 0
  fi
  # Le portail central relaie par le réseau maillé (100.64/10) : son IP d'abord, sinon la
  # cible imposée par EXPOSE_TARGET_HOST, sinon la première IP globale.
  target_ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 \
    | grep -E '^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.' | head -1 || true)"
  target_ip="${EXPOSE_TARGET_HOST:-${target_ip:-$(ip -4 -o addr show scope global | awk 'NR==1{print $4}' | cut -d/ -f1)}}"
  if [[ ! "$target_ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
    echo "AVERTISSEMENT : adresse cible introuvable, déclaration ignorée"
    return 0
  fi
  body="$(printf '{"workspace":"%s","service":"%s","host":"%s","target_host":"%s","target_port":%d,"scheme":"http","entry_path":""}' \
    "$workspace" "$SERVICE_NAME" "$host" "$target_ip" "$HTTP_PORT")"
  # Le jeton passe par une config curl lue sur stdin, jamais en argument (`ps auxww`).
  local response public_url
  response="$(curl -sS -w '\n%{http_code}' --max-time 15 -X PUT \
    -H 'Content-Type: application/json' -d "$body" "${portal%/}/me/expositions" \
    -K - 2>/dev/null <<<"header = \"Authorization: Bearer ${PORTAL_TOKEN}\"" || true)"
  http_code="${response##*$'\n'}"
  if [[ "$http_code" =~ ^2[0-9][0-9]$ ]]; then
    # On rend l'URL et le verdict du portail, pas un nom reconstruit ici : un 200 dit que
    # l'entrée existe, pas que le portail atteint le service (« joignable »).
    public_url="$(grep -oE '"url":"https://[A-Za-z0-9.-]+"' <<<"$response" | cut -d'"' -f4 || true)"
    echo "service déclaré à l'annuaire : ${public_url:-URL non rendue} → $target_ip:$HTTP_PORT"
    # L'adresse publique sert d'URL de retour OIDC. Prise une fois de l'annuaire, puis
    # figée dans .env : c'est ce que le fournisseur a enregistré comme redirection admise.
    if [[ -n "$public_url" ]] && ! grep -q '^MILES_PUBLIC_URL=.\+' "$ENV_FILE"; then
      sed -i '/^MILES_PUBLIC_URL=/d' "$ENV_FILE"
      echo "MILES_PUBLIC_URL=$public_url" >> "$ENV_FILE"
      echo "adresse publique inscrite dans .env : $public_url"
    fi
    # Le verdict porte sur la stack EN PLACE : la déclaration précède la construction
    # parce que le code TOTP expire en 30 s. Au premier passage rien n'écoute encore,
    # d'où un faux négatif.
    if ! grep -q '"joignable":true' <<<"$response"; then
      echo "AVERTISSEMENT : le portail ne joint pas $target_ip:$HTTP_PORT (normal au premier déploiement, la stack n'est pas encore lancée ; sinon, réseau maillé à vérifier)"
    fi
  else
    echo "AVERTISSEMENT : déclaration de $workspace-$SERVICE_NAME refusée (HTTP ${http_code:-000}) ; elle se rejouera au prochain passage"
  fi
}
step 4 "déclaration à l'annuaire du portail"
grep -q "^name: $SERVICE_NAME\$" "$PRODUIT_DIR/docker-compose.yml" \
  || fail "SERVICE_NAME ($SERVICE_NAME) diffère du name: de docker-compose.yml"
declare_exposition
# Code à usage unique : rien en aval n'en a besoin, et il ne doit atteindre aucun conteneur.
unset PORTAL_TOKEN

# --- 4. Construire, arrêter, relancer --------------------------------------------------
step 5 "construction des images depuis la copie du dépôt"
# Jamais sautée : c'est ici, sur copie fraîche, qu'on prouve que les images se bâtissent.
compose build --pull || fail "construction en échec : défaut du dépôt, à corriger d'abord"

# --- Compte d'amorçage de la machine de test, créé une seule fois ------------------------
# Sur une machine de test, l'administrateur existe dès le premier démarrage : les tests
# d'intégration s'authentifient sans passer par l'écran d'amorçage. Jamais régénéré ; pour
# repartir de zéro, retirer les trois entrées MILES_ADMIN_* de .env.
# Ce compte est PROPRE au module d'environnement : ceux des deux autres produits n'ouvrent
# rien ici.
step 6 "compte d'amorçage"
if grep -q '^MILES_ADMIN_' "$ENV_FILE"; then
  echo "compte d'amorçage déjà déclaré dans .env, conservé"
else
  admin_password="$(openssl rand -base64 24)"
  # Mot de passe par stdin, jamais en argument : l'argv se lit par `ps`.
  admin_hash="$(printf '%s\n' "$admin_password" \
    | compose run --rm --no-deps -T backend environnement-admin hash-password)" \
    || fail "empreinte du mot de passe d'amorçage impossible"
  admin_email="${MILES_ADMIN_EMAIL:-admin@environnement.invalid}"
  admin_username="${MILES_ADMIN_USERNAME:-admin}"
  # Les trois entrées d'un seul coup : un compte partiel ferait refuser le démarrage.
  # Apostrophes : compose n'interpole pas les `$` de l'empreinte argon2id.
  printf "MILES_ADMIN_EMAIL='%s'\nMILES_ADMIN_USERNAME='%s'\nMILES_ADMIN_PASSWORD_HASH='%s'\n" \
    "$admin_email" "$admin_username" "$admin_hash" >> "$ENV_FILE"
  # Le clair n'est rendu qu'aux tests de cette machine, jamais journalisé.
  (umask 077 && printf '%s\n' "$admin_password" > "$ADMIN_PASSWORD_FILE")
  unset admin_password
  echo "compte d'amorçage '$admin_username' créé ; mot de passe dans $ADMIN_PASSWORD_FILE"
fi

step 7 "arrêt de la stack (orphelins compris)"
compose down --remove-orphans

# --- 5. Conflit de port, APRÈS l'arrêt -------------------------------------------------
# Sondé avant l'arrêt, le port serait pris… par notre propre service.
if (exec 3<>"/dev/tcp/127.0.0.1/$HTTP_PORT") 2>/dev/null; then
  fail "port $HTTP_PORT occupé par un autre service (ss -ltnp 'sport = :$HTTP_PORT')"
fi
compose up -d

# --- 6. Attendre un conteneur réellement exécutable avant de migrer --------------------
step 8 "attente du conteneur backend"
stable=0
for _ in $(seq 1 "$CONTAINER_WAIT_S"); do
  state="$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' "$(compose ps -q backend)" 2>/dev/null || true)"
  if [[ "$state" == "running "* ]]; then stable=$((stable + 1)); else stable=0; fi
  # Trois secondes consécutives en marche : un conteneur qui redémarre en boucle ne passe pas.
  [[ "$stable" -ge 3 ]] && break
  sleep 1
done
[[ "$stable" -ge 3 ]] || fail "backend jamais stable : docker compose logs backend"

step 9 "migrations puis vérification de la version de schéma"
compose exec -T backend environnement-migrate apply || fail "migration en échec : docker compose logs backend"
# « apply » peut sortir en succès sans avoir atteint la dernière version (base tamponnée
# à la main) : on interroge le résultat, pas le code de retour.
compose exec -T backend environnement-migrate status || fail "schéma en retard après migration"

# --- 7. Contrôle de santé final, plafonné ----------------------------------------------
step 10 "contrôle de santé sur le port publié $HTTP_PORT"
# Par le frontend nginx, sur le port réellement exposé : valide aussi le proxy /api.
healthy=0
for _ in $(seq 1 "$HEALTH_WAIT_S"); do
  if curl -fsS "http://127.0.0.1:$HTTP_PORT/api/health" >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done
[[ "$healthy" -eq 1 ]] || fail "santé KO après ${HEALTH_WAIT_S}s : curl -s http://127.0.0.1:$HTTP_PORT/api/health"
echo "déploiement OK : $(git -C "$DEPOT_DIR" rev-parse --short HEAD) sur http://$(hostname):$HTTP_PORT"

# --- 8. Récupération d'espace disque, au plus une fois par semaine ---------------------
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
