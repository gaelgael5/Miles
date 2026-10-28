#!/usr/bin/env bash
# Livraison du module d'enrolement sur machine de test : seule voie de déploiement (voir
# CLAUDE.md et la skill test-machine-deployment).
#
#   ./dev-deploy.sh                       déploiement normal (idempotent, rejouable)
#   MILES_HTTP_PORT=8181 ./dev-deploy.sh  premier passage sur un port autre que 8081
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
# la machine de test dans le portail ne retrouve pas la stack. Distinct de celui des deux
# autres produits, les trois stacks cohabitant sur la même machine.
SERVICE_NAME="miles-enrolement"
CONTAINER_WAIT_S=90
HEALTH_WAIT_S=120
PURGE_EVERY_S=$((7 * 24 * 3600))

# Les GARDES viennent du socle, la SÉQUENCE reste ici (décision de Gael du 28/10/2026).
# Chaque garde encode une panne mesurée et était écrite trois fois ; elle se répare
# maintenant en un endroit. La séquence, elle, reste lisible d'un bout à l'autre de ce
# fichier, et une erreur dedans ne casse que ce produit — le script de déploiement est la
# seule voie de livraison du projet.
# shellcheck source=../socle/deploy/gardes.sh
source "$DEPOT_DIR/socle/deploy/gardes.sh"
socle_exige PRODUIT_DIR DEPOT_DIR BRANCH STATE_DIR ENV_FILE TOTAL_STEPS SERVICE_NAME

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

# --- 0. Survivre à la perte de la session -----------------------------------------------
socle_journal_et_filet "$LOG_FILE" "$NO_NOHUP"

if [[ "$BOOTSTRAP_KEY" -eq 1 && -z "${MILES_DEPLOY_REEXEC:-}" ]]; then
  socle_bootstrap_cle_de_deploiement "$DEPLOY_KEY" "$FORCE"
fi

socle_step 1 "prérequis"
socle_prerequis

socle_step 2 "mise à jour depuis origin/$BRANCH"
socle_depot_a_jour "$PRODUIT_DIR/dev-deploy.sh" "$@"

socle_step 3 "configuration (.env)"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
socle_valeur_durable MILES_DB_PASSWORD "$(openssl rand -hex 24)" \
  "mot de passe de base généré"
socle_valeur_durable MILES_SECRETS_KEY "$(openssl rand -base64 32 | tr '+/' '-_')" \
  "clé des secrets générée"
# Machines de test partagées : le portail occupe souvent 8080 et un autre produit 8081,
# d'où un défaut distinct et un port choisi au premier passage.
socle_persist_default MILES_HTTP_PORT 8081
socle_persist_default EXPOSE_PORTAL_URL
socle_persist_default EXPOSE_WORKSPACE
socle_persist_default EXPOSE_HOST "$(hostname)"
HTTP_PORT="$(socle_env_value MILES_HTTP_PORT)"
[[ "$HTTP_PORT" =~ ^[0-9]{2,5}$ ]] || socle_fail "MILES_HTTP_PORT invalide dans .env : $HTTP_PORT"
# .env et .env.bak sont montés FICHIER PAR FICHIER dans le backend, qui y écrit le compte
# d'amorçage. Un fichier monté doit exister : absent, docker créerait un dossier à sa
# place. Ils appartiennent à l'utilisateur non root du runtime, seul à devoir y écrire ;
# root, qui lance ce script et compose, les lit de toute façon.
touch "$BACKUP_ENV_FILE"
chmod 600 "$ENV_FILE" "$BACKUP_ENV_FILE"
chown "$RUNTIME_UID:$RUNTIME_UID" "$ENV_FILE" "$BACKUP_ENV_FILE" \
  || socle_fail "chown de .env impossible : lancer dev-deploy.sh en root (machine de test)"

# --- Mode destructif isolé : drapeau explicite, confirmation, court-circuit -------------
if [[ "$RESET_DB" -eq 1 ]]; then
  read -r -p "Taper « detruire enrolement » pour supprimer définitivement la base : " answer
  [[ "$answer" == "detruire enrolement" ]] || socle_fail "confirmation refusée, rien n'a été touché"
  socle_compose down --volumes --remove-orphans
  echo "base détruite ; relancer ./dev-deploy.sh pour redéployer."
  exit 0
fi

socle_step 4 "déclaration à l'annuaire du portail"
socle_declaration_annuaire
# Code à usage unique : rien en aval n'en a besoin, et il ne doit atteindre aucun conteneur.
unset PORTAL_TOKEN

socle_step 5 "construction des images depuis la copie du dépôt"
# Jamais sautée : c'est ici, sur copie fraîche, qu'on prouve que les images se bâtissent.
socle_compose build --pull \
  || socle_fail "construction en échec : défaut du dépôt, à corriger d'abord"

socle_step 6 "compte d'amorçage"
socle_compte_d_amorcage "enrolement-admin" "admin@enrolement.invalid" "$ADMIN_PASSWORD_FILE"

socle_step 7 "arrêt de la stack (orphelins compris)"
socle_compose down --remove-orphans

# Sondé APRÈS l'arrêt : avant, le port serait pris… par notre propre service.
socle_port_libre "$HTTP_PORT"
socle_compose up -d

socle_step 8 "attente du conteneur backend"
socle_conteneur_stable backend "$CONTAINER_WAIT_S"

socle_step 9 "migrations puis vérification de la version de schéma"
socle_migrations_appliquees "enrolement-migrate"
socle_schema_a_jour "enrolement-migrate"

socle_step 10 "contrôle de santé sur le port publié $HTTP_PORT"
socle_sante "$HTTP_PORT" "$HEALTH_WAIT_S"
echo "déploiement OK : $(git -C "$DEPOT_DIR" rev-parse --short HEAD) sur http://$(hostname):$HTTP_PORT"

socle_purge_hebdomadaire "$PURGE_STAMP" "$PURGE_EVERY_S"
