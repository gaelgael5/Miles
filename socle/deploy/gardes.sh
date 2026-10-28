# shellcheck shell=bash
# Gardes de déploiement partagées par les trois produits de Miles.
#
# DÉCISION DE GAEL DU 28/10/2026 : on partage les GARDES, pas la SÉQUENCE.
#
# Chaque fonction ci-dessous encode une panne mesurée, et chacune était écrite trois fois.
# Corriger l'une des trois et oublier les deux autres est précisément ce qui s'est déjà
# produit dans ce dépôt — un commentaire faux recopié d'un produit à l'autre. Une garde se
# répare donc en un endroit.
#
# La séquence, elle, reste dans `<produit>/dev-deploy.sh` : ses étapes numérotées, ses
# messages, ses valeurs propres. Deux raisons, et la seconde est la plus importante : les
# produits diffèrent vraiment par leur séquence (le portail a un broker, les ports et les
# noms de commande changent), et une erreur dans la séquence ne casse alors qu'UN produit.
# Le script de déploiement est la seule voie de livraison du projet : borner le rayon d'une
# faute y vaut plus que supprimer des lignes.
#
# OPTIONS ÉCARTÉES, à ne pas rouvrir : tout partager — une erreur casserait les trois
# déploiements à la fois ; ne rien partager — les gardes restaient triplicables.
#
# Les fonctions portent le préfixe `socle_` pour qu'on voie, à l'appel, ce qui vient d'ici
# et ce qui appartient au produit. Elles lisent des variables que le produit pose avant de
# sourcer ce fichier ; `socle_exige` refuse de travailler si l'une manque.

# --- Garde de la garde ------------------------------------------------------------------
# Une variable attendue et non posée ferait travailler une garde sur une chaîne vide — elle
# passerait au vert sans rien garder. On échoue à la place, en nommant la variable.
socle_exige() {
  local nom
  for nom in "$@"; do
    if [[ -z "${!nom:-}" ]]; then
      echo "ÉCHEC : $nom n'est pas posée avant l'appel des gardes du socle" >&2
      exit 1
    fi
  done
}

socle_step() { echo "==> [$1/$TOTAL_STEPS] $2"; }
socle_fail() { echo "ÉCHEC : $*" >&2; exit 1; }
socle_compose() {
  docker compose --project-directory "$PRODUIT_DIR" --env-file "$ENV_FILE" "$@"
}
socle_env_value() { grep "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

# Valeur non secrète prise dans l'environnement au premier passage, puis figée : .env fait foi.
socle_persist_default() {
  local key="$1" default="${2:-}"
  local value="${!key:-$default}"
  grep -q "^$key=" "$ENV_FILE" && return 0
  [[ -n "$value" ]] && echo "$key=$value" >> "$ENV_FILE"
  return 0
}

# --- Survivre à la perte de la session --------------------------------------------------
# PANNE RÉELLE : le script arrête la stack ; lancé depuis une session qu'elle héberge (ou
# une connexion mobile qui tombe), le SIGHUP l'a tué entre l'arrêt et le redémarrage —
# base et journaux seuls, application absente, migrations jamais jouées.
socle_journal_et_filet() {
  local log_file="$1" no_nohup="$2"
  mkdir -p "$STATE_DIR"
  if [[ "$no_nohup" -eq 0 && -z "${MILES_DEPLOY_LOGGING:-}" ]]; then
    trap '' HUP
    export MILES_DEPLOY_LOGGING=1
    # `exec` sans commande redirige le shell COURANT, donc tout le script, bien qu'appelé
    # depuis une fonction. Le journal survit à la fenêtre qui disparaît.
    exec > >(tee -a "$log_file") 2>&1
    echo "journal : $log_file"
  fi
}

# --- Clé de déploiement engendrée SUR l'hôte --------------------------------------------
# La clé privée ne quitte jamais l'hôte : seule la publique est affichée, en dernier. Une
# clé privée recopiée à la main casse typiquement en « error in libcrypto », et elle finit
# dans un historique de terminal.
socle_bootstrap_cle_de_deploiement() {
  local deploy_key="$1" force="$2"
  if [[ -f "$deploy_key" && "$force" -eq 0 ]]; then
    echo "clé existante conservée (--force pour régénérer)."
  else
    rm -f "$deploy_key" "$deploy_key.pub"
    ssh-keygen -q -t ed25519 -N "" -C "miles-deploy@$(hostname)" -f "$deploy_key"
  fi
  if ! grep -q "$(basename "$deploy_key")" "$HOME/.ssh/config" 2>/dev/null; then
    printf '\nHost github.com\n  IdentityFile %s\n  IdentitiesOnly yes\n' "$deploy_key" \
      >> "$HOME/.ssh/config"
  fi
  echo "Enregistrer cette clé dans GitHub > Settings > Deploy keys (lecture seule) :"
  cat "$deploy_key.pub"
  read -r -p "Appuyer sur Entrée une fois la clé enregistrée pour poursuivre le déploiement… " _
}

# --- Prérequis, avec la commande d'installation -----------------------------------------
# Un message qui dit seulement « introuvable » impose un aller-retour ; celui qui porte la
# commande d'installation n'en impose aucun.
socle_prerequis() {
  command -v git >/dev/null || socle_fail "git absent : sudo apt-get install -y git"
  command -v docker >/dev/null \
    || socle_fail "docker absent : https://docs.docker.com/engine/install/debian/"
  docker compose version >/dev/null 2>&1 \
    || socle_fail "plugin compose absent : sudo apt-get install -y docker-compose-plugin"
  command -v curl >/dev/null || socle_fail "curl absent : sudo apt-get install -y curl"
  command -v openssl >/dev/null || socle_fail "openssl absent : sudo apt-get install -y openssl"
  docker info >/dev/null 2>&1 \
    || socle_fail "démon docker injoignable : sudo usermod -aG docker \$USER, puis se reconnecter"
}

# --- Mise à jour depuis le dépôt, puis ré-exécution -------------------------------------
# Sans la ré-exécution, on déploie du code neuf avec un script, un compose et un Dockerfile
# périmés — pannes incompréhensibles garanties. Il n'existe pas de mode « déploie ce qui est
# déjà là » : le réseau et l'accès au dépôt sont un prérequis, assumé.
socle_depot_a_jour() {
  local script="$1"
  shift
  socle_exige DEPOT_DIR BRANCH
  git -C "$DEPOT_DIR" fetch origin "$BRANCH" \
    || socle_fail "récupération impossible (accès au dépôt ? dépôt privé : --bootstrap-deploy-key)"
  [[ "$(git -C "$DEPOT_DIR" branch --show-current)" == "$BRANCH" ]] \
    || socle_fail "la copie n'est pas sur $BRANCH : git -C $DEPOT_DIR checkout $BRANCH"
  local avant
  avant="$(git -C "$DEPOT_DIR" rev-parse HEAD)"
  git -C "$DEPOT_DIR" merge --ff-only "origin/$BRANCH" \
    || socle_fail "copie locale divergente d'origin/$BRANCH : aucune retouche locale n'est admise ici"
  if [[ "$avant" != "$(git -C "$DEPOT_DIR" rev-parse HEAD)" && -z "${MILES_DEPLOY_REEXEC:-}" ]]; then
    echo "nouvelle version récupérée, ré-exécution du script à jour"
    # `exec` remplace le processus : la suite du script d'appel n'est pas exécutée.
    MILES_DEPLOY_REEXEC=1 exec "$script" "$@"
  fi
}

# --- Valeur durable : engendrée une fois, JAMAIS régénérée ------------------------------
# Un mot de passe de base régénéré casserait la base déjà initialisée avec l'ancien. Et
# MILES_SECRETS_KEY régénérée rendrait illisibles tous les secrets chiffrés en base — dont
# le secret client de chaque connecteur OIDC et, pour le module d'environnement, la clé
# privée de signature dont dépend l'appariement des devices.
# La valeur est ENGENDRÉE PAR L'APPELANT et passée en argument, plutôt qu'une commande à
# évaluer ici : pas d'`eval`, et la valeur reste un argument de fonction — que `ps` ne voit
# pas, contrairement à l'argv d'un programme externe. Elle est engendrée à chaque passage et
# jetée si une valeur existe déjà, ce qui ne coûte rien et garde la garde simple.
socle_valeur_durable() {
  local clef="$1" valeur="$2" libelle="$3"
  if ! grep -q "^$clef=.\+" "$ENV_FILE"; then
    # La ligne vide ou tronquée d'un passage interrompu est retirée avant d'écrire.
    sed -i "/^$clef=/d" "$ENV_FILE"
    echo "$clef=$valeur" >> "$ENV_FILE"
    echo "$libelle (première exécution)"
  fi
}

# --- Conflit de port, APRÈS l'arrêt de la stack -----------------------------------------
# PANNE RÉELLE : sondé AVANT l'arrêt, le port était pris… par notre propre service. Le repli
# s'appliquait à tort, se persistait dans la configuration, et le tunnel public pointait
# toujours sur l'ancien port — site dans le vide.
socle_port_libre() {
  local port
  for port in "$@"; do
    if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
      socle_fail "port $port occupé par un autre service (ss -ltnp 'sport = :$port')"
    fi
  done
}

# --- Attendre un conteneur réellement exécutable avant de migrer ------------------------
# PANNE RÉELLE : juste après le lancement, un conteneur peut encore démarrer ou redémarrer
# en boucle. Sans attente, la migration échoue, l'arrêt sur erreur avorte le déploiement
# AVANT la migration, et la stack reste servie avec un schéma en retard — panne silencieuse,
# le contrôle de santé qui suit ne testant pas le schéma.
socle_conteneur_stable() {
  local service="$1" plafond="$2" stable=0 etat
  for _ in $(seq 1 "$plafond"); do
    etat="$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' \
      "$(socle_compose ps -q "$service")" 2>/dev/null || true)"
    if [[ "$etat" == "running "* ]]; then stable=$((stable + 1)); else stable=0; fi
    # Trois secondes consécutives en marche : un conteneur qui redémarre en boucle ne passe
    # pas. Décider DANS la boucle, et non en re-posant la question après coup — re-poser une
    # question qu'on vient de trancher est un TOCTOU, pas une précaution.
    [[ "$stable" -ge 3 ]] && break
    sleep 1
  done
  [[ "$stable" -ge 3 ]] || socle_fail "$service jamais stable : docker compose logs $service"
}

# --- Migrer, puis vérifier que le schéma est réellement à jour --------------------------
# DEUX fonctions et non une, pour que le produit garde le découpage de SA séquence : le
# portail en fait deux étapes numérotées, les deux coquilles une seule. La garde ne décide
# pas de la forme du journal de déploiement.
socle_migrations_appliquees() {
  socle_compose exec -T backend "$1" apply \
    || socle_fail "migration en échec : docker compose logs backend"
}

# PANNE RÉELLE : « apply » peut sortir en SUCCÈS sans avoir atteint la dernière version —
# typiquement sur une base tamponnée à la main. On interroge le RÉSULTAT, pas le code de
# retour : `status` échoue si le schéma est en retard. Ne jamais supprimer cet appel au
# motif que la migration a « réussi ».
socle_schema_a_jour() {
  socle_compose exec -T backend "$1" status \
    || socle_fail "schéma en retard après migration"
}

# --- Contrôle de santé final, plafonné --------------------------------------------------
# Sans plafond, un service qui ne démarre jamais fait attendre indéfiniment. Interrogé sur
# le port réellement PUBLIÉ, à travers le nginx du front : ça valide aussi le relais /api.
socle_sante() {
  local port="$1" plafond="$2" ok=0
  for _ in $(seq 1 "$plafond"); do
    if curl -fsS "http://127.0.0.1:$port/api/health" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
  done
  [[ "$ok" -eq 1 ]] \
    || socle_fail "santé KO après ${plafond}s : curl -s http://127.0.0.1:$port/api/health"
}

# --- Récupération d'espace disque, au plus une fois par semaine -------------------------
# PANNE RÉELLE : chaque déploiement reconstruit les images ; les couches précédentes sont
# détaggées mais restent sur le disque, et rien ne les récupère. Une machine sans espace
# n'arrive plus à relancer la stack qu'elle vient d'arrêter — en plein déploiement
# (host-test-36, 95 %, 11 Go de cache).
#
# Quatre bornes, toutes nécessaires : la FRÉQUENCE (un témoin horodaté, sinon la purge
# ajoute des minutes à chaque passage et finit par être désactivée « le temps de ») ; la
# POSITION (après le contrôle de santé, pour ne pas retarder la mise à disposition) ; la
# PORTÉE (cache de construction et images détaggées, jamais les volumes qui portent les
# données, jamais une purge globale qui supprimerait les images de base) ; et le CODE DE
# RETOUR, qui ne doit jamais faire échouer le déploiement.
socle_purge_hebdomadaire() {
  local temoin="$1" periode="$2" maintenant derniere avant_kb apres_kb
  maintenant="$(date +%s)"
  derniere="$(cat "$temoin" 2>/dev/null || echo 0)"
  if ((maintenant - derniere > periode)); then
    {
      avant_kb="$(df -k --output=avail /var/lib/docker 2>/dev/null | tail -1 || echo 0)"
      docker builder prune -f >/dev/null && docker image prune -f >/dev/null
      apres_kb="$(df -k --output=avail /var/lib/docker 2>/dev/null | tail -1 || echo 0)"
      echo "purge hebdomadaire : $(((apres_kb - avant_kb) / 1024)) Mo récupérés"
      echo "$maintenant" > "$temoin"
    } || echo "purge en échec (sans effet sur le déploiement)"
  fi
}

# --- Déclaration à l'annuaire du portail, best-effort -----------------------------------
# Appelée AVANT la construction, pas après le contrôle de santé : le code TOTP vit ~30 s et
# serait périmé au bout d'un build de plusieurs minutes. La déclaration est un upsert
# idempotent ; publier une stack pas encore debout est sans effet. Rien ici ne fait échouer
# le déploiement — d'où les AVERTISSEMENT plutôt que des échecs.
socle_declaration_annuaire() {
  socle_exige SERVICE_NAME HTTP_PORT ENV_FILE PRODUIT_DIR
  grep -q "^name: $SERVICE_NAME\$" "$PRODUIT_DIR/docker-compose.yml" \
    || socle_fail "SERVICE_NAME ($SERVICE_NAME) diffère du name: de docker-compose.yml"
  local portal workspace host target_ip body http_code response public_url
  portal="$(socle_env_value EXPOSE_PORTAL_URL)"
  workspace="$(socle_env_value EXPOSE_WORKSPACE)"
  host="$(socle_env_value EXPOSE_HOST)"
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
        || ! "$workspace" =~ ^[a-z0-9][a-z0-9-]*$ \
        || ! "$host" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
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
    # Le verdict porte sur la stack EN PLACE : la déclaration précède la construction parce
    # que le code TOTP expire en 30 s. Au premier passage rien n'écoute encore, d'où un
    # faux négatif annoncé comme tel.
    if ! grep -q '"joignable":true' <<<"$response"; then
      echo "AVERTISSEMENT : le portail ne joint pas $target_ip:$HTTP_PORT (normal au premier déploiement, la stack n'est pas encore lancée ; sinon, réseau maillé à vérifier)"
    fi
  else
    echo "AVERTISSEMENT : déclaration de $workspace-$SERVICE_NAME refusée (HTTP ${http_code:-000}) ; elle se rejouera au prochain passage"
  fi
}

# --- Compte d'amorçage de la machine de test, créé une seule fois -----------------------
# Sur une machine de test, l'administrateur existe dès le premier démarrage : les tests
# d'intégration s'authentifient sans passer par l'écran d'amorçage. Jamais régénéré ; pour
# repartir de zéro, retirer les trois entrées MILES_ADMIN_* de .env. Ce compte est PROPRE au
# produit : celui d'un autre n'ouvre rien chez lui.
socle_compte_d_amorcage() {
  local commande_admin="$1" email_defaut="$2" fichier_mot_de_passe="$3"
  if grep -q '^MILES_ADMIN_' "$ENV_FILE"; then
    echo "compte d'amorçage déjà déclaré dans .env, conservé"
    return 0
  fi
  local mot_de_passe empreinte email utilisateur
  mot_de_passe="$(openssl rand -base64 24)"
  # Mot de passe par stdin, jamais en argument : l'argv se lit par `ps auxww`.
  empreinte="$(printf '%s\n' "$mot_de_passe" \
    | socle_compose run --rm --no-deps -T backend "$commande_admin" hash-password)" \
    || socle_fail "empreinte du mot de passe d'amorçage impossible"
  email="${MILES_ADMIN_EMAIL:-$email_defaut}"
  utilisateur="${MILES_ADMIN_USERNAME:-admin}"
  # Les trois entrées d'un seul coup : un compte partiel ferait refuser le démarrage.
  # Apostrophes : compose n'interpole pas les `$` de l'empreinte argon2id.
  printf "MILES_ADMIN_EMAIL='%s'\nMILES_ADMIN_USERNAME='%s'\nMILES_ADMIN_PASSWORD_HASH='%s'\n" \
    "$email" "$utilisateur" "$empreinte" >> "$ENV_FILE"
  # Le clair n'est rendu qu'aux tests de cette machine, jamais journalisé.
  (umask 077 && printf '%s\n' "$mot_de_passe" > "$fichier_mot_de_passe")
  unset mot_de_passe
  echo "compte d'amorçage '$utilisateur' créé ; mot de passe dans $fichier_mot_de_passe"
}
