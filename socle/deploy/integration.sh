# shellcheck shell=bash
# Gardes des campagnes d'intégration, partagées par les trois produits.
#
# Même décision que pour le déploiement (Gael, 28/10/2026) : on partage les GARDES, pas la
# séquence. Ce qui suit encode une panne mesurée ; le reste de chaque
# `<produit>/scripts/run-integration-tests.sh` — ses ressources jetables, ses doublures de
# fournisseur, ses invocations de pytest — reste chez lui, parce que c'est là que les trois
# produits diffèrent vraiment : le portail lance une forge git et un courtier MQTT, les deux
# autres un fournisseur OIDC jetable.

# La garde d'espace est partagée avec le déploiement : une campagne bâtit des images
# comme lui, et le disque ne fait pas la différence. Elle vit dans son propre fichier
# plutôt que dans `gardes.sh`, qu'une campagne n'a pas à sourcer en entier.
# shellcheck source=espace.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/espace.sh"

socle_it_docker_present() {
  command -v docker >/dev/null \
    || { echo "docker introuvable : voir https://docs.docker.com/engine/install/" >&2; exit 1; }
}

# --- Ce que la campagne ÉPROUVE, annoncé en tête et rappelé au pied ---------------------
# PANNE MESURÉE le 22/11/2026 (bug `18b6f722`) : deux campagnes du portail ont rendu
# « vert » sur un arbre de travail vieux de trois commits, et l'une des deux a servi à
# annoncer une validation qui était fausse.
#
# `run-integration-tests.sh` ne met PAS le dépôt à jour, contrairement à `dev-deploy.sh`
# (`socle_depot_a_jour`), et c'est VOLONTAIRE : on lance une campagne précisément pour
# éprouver ce qui n'est pas encore poussé. Ce qui manquait n'était donc pas une mise à
# jour — c'est que l'écart se LISE. Ces deux gardes ne changent rien à ce que la campagne
# exécute, et ne refusent jamais de tourner sur un arbre modifié.
#
# ON ANNONCE CE QUE PORTE `HEAD`, JAMAIS UNE RÉFÉRENCE DISTANTE. La commande lancée ce
# jour-là affichait `git log origin/dev` après un `fetch` : l'empreinte affichée était la
# bonne, et la campagne éprouvait autre chose. L'écart avec `origin/<branche>` est donc dit
# pour ce qu'il est — la dernière référence connue LOCALEMENT, sans `fetch` : une campagne
# ne va pas au réseau pour se décrire, et c'est une référence fraîche qui a trompé.
#
# JAMAIS BLOQUANTE : hors dépôt git, ou sans git installé, l'annonce le dit et la campagne
# continue. Une garde d'information qui fait échouer une campagne se fait retirer.
socle_it_source_eprouvee() {
  local depot="$1" branche distante ecart modifies
  # Variable GLOBALE, et c'est délibéré : `socle_it_verdict_final` la rappelle depuis le
  # piège de sortie de l'appelant, où rien ne lui est passé en argument.
  SOCLE_IT_SOURCE="source inconnue"
  if ! command -v git >/dev/null || ! git -C "$depot" rev-parse --git-dir >/dev/null 2>&1; then
    echo "==> campagne sur : $SOCLE_IT_SOURCE ($depot n'est pas un dépôt git lisible)"
    return 0
  fi
  SOCLE_IT_SOURCE="$(git -C "$depot" log -1 --format='%h %s' 2>/dev/null || echo 'HEAD sans commit')"
  branche="$(git -C "$depot" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '(détachée)')"
  distante="origin/$branche"
  echo "==> campagne sur : $SOCLE_IT_SOURCE"
  if git -C "$depot" rev-parse --verify --quiet "$distante" >/dev/null; then
    ecart="$(git -C "$depot" rev-list --left-right --count "HEAD...$distante" 2>/dev/null || echo '? ?')"
    echo "    branche $branche : ${ecart%%[[:space:]]*} commit(s) d'avance, ${ecart##*[[:space:]]} de retard sur $distante — référence connue LOCALEMENT, aucun fetch ici"
  else
    echo "    branche $branche : aucune référence locale pour $distante"
  fi
  modifies="$(git -C "$depot" status --porcelain 2>/dev/null | wc -l || true)"
  if [ "$modifies" -gt 0 ]; then
    echo "    arbre de travail : $modifies fichier(s) en écart (modifiés ou non suivis) — usage normal, mais ce n'est plus exactement le commit annoncé"
  else
    echo "    arbre de travail : propre"
  fi
}

# Rappelé par le piège de SORTIE de l'appelant, donc vraie dernière ligne de la sortie —
# échec, interruption et succès compris. Deux raisons mesurées le 22/11/2026 : une campagne
# se relit par la fin, et un tube vers `tail` ne garde que celle-là.
socle_it_verdict_final() {
  local code="$1" verdict
  if [ "$code" -eq 0 ]; then
    verdict="SUCCÈS"
  else
    verdict="ÉCHEC"
  fi
  # `:-` : le piège peut s'exécuter AVANT l'annonce (docker absent, interruption au
  # démarrage), et `set -u` ferait alors échouer le nettoyage lui-même.
  echo "==> campagne terminée sur ${SOCLE_IT_SOURCE:-source inconnue} — verdict : $verdict (code $code)"
}

# --- Tout ce qu'une campagne lance doit pouvoir être retiré à la sortie ------------------
# PANNE MESURÉE le 22/11/2026 (bug `db3bccb9`) : une campagne arrêtée a laissé tourner son
# conteneur de pytest huit minutes de plus, et avec lui le réseau jetable et l'image. Le
# piège ne retirait que les conteneurs qu'il pouvait NOMMER (`$RUN_ID-db`, `-mqtt`…) ; les
# conteneurs de test et les sondes étaient lancés en `--rm` SANS `--name`, donc baptisés au
# hasard par Docker (`blissful_kirch`). `--rm` ne les retire que quand ILS sortent, et un
# `kill` du script ne les touche pas : ce sont des processus du démon, pas des enfants du
# script. Le `docker network rm` échouait alors sur « active endpoints », et le `|| true` du
# nettoyage avalait l'échec. C'est aussi la cause — restée inconnue jusque-là — des quatre
# conteneurs survivants du 07/11/2026 notés dans `LESSONS.md`.
#
# ON RETIRE PAR ÉTIQUETTE, PAS PAR LISTE DE NOMS. Une liste tenue à la main est ce qui a
# produit la panne : il y manquait trois `docker run` sur sept. L'étiquette est posée par
# chaque `docker run` de la campagne, et `tests/architecture/test_campagnes.py` rougit si un
# seul l'oublie. Les NOMS restent dérivés de `$RUN_ID` pour une autre raison : la machine de
# test est TRANSVERSE, et un relevé d'état doit pouvoir attribuer ce qu'il trouve.
#
# L'ORDRE COMPTE : les conteneurs d'abord, le réseau ensuite — un réseau dont un point de
# terminaison est encore actif ne se retire pas.
socle_it_ressources_jetables_retirees() {
  local run_id="$1"
  # `-v` et pas seulement `-f` : les images de ces services déclarent des volumes ANONYMES
  # (le `VOLUME` de `postgres`, de `gitea`) que `docker rm` sans `-v` laisse derrière.
  # Mesuré sur test1 le 29/10/2026 : 249 volumes orphelins, 7,9 Go dont 97 % récupérables,
  # pour un disque à 82 %. La purge de `dev-deploy.sh` ne les couvre pas, et c'est
  # délibéré : elle ne touche jamais aux volumes, qui portent des données de travail.
  docker ps -aq --filter "label=miles-campagne=$run_id" 2>/dev/null \
    | xargs -r docker rm -f -v >/dev/null 2>&1 || true
  docker network rm "$run_id" >/dev/null 2>&1 || true
}

# --- Attendre un PostgreSQL jetable réellement prêt -------------------------------------
# CAUSE ÉTABLIE le 27/10/2026, reproduite 6 fois sur 6, des sept échecs « jamais prêt » du
# 24 au 27/10 — et elle était dans NOTRE script, pas dans la machine ni dans postgres.
#
# L'entrypoint de `postgres:16` lance un serveur TEMPORAIRE pendant initdb, qui n'écoute QUE
# la socket Unix. `pg_isready` y répond « accepting connections », puis REPASSE en échec
# quand l'entrypoint arrête ce serveur pour démarrer le vrai. L'ancienne boucle sortait sur
# ce premier succès, puis posait une SECONDE sonde indépendante : quand celle-ci tombait
# dans la fenêtre d'arrêt, le script annonçait « jamais prêt après 180 s » au bout de
# quelques secondes — d'où un journal de 77 octets et une intermittence qui ne dépendait que
# de l'instant de cette seconde sonde.
#
# Deux corrections, et les deux comptent :
#   `-h 127.0.0.1` force la sonde en TCP, que le serveur temporaire n'expose pas — il devient
#   donc invisible, au lieu d'être pris pour le vrai ;
#   la décision se prend DANS la boucle, sur trois succès consécutifs, au lieu d'être rejouée
#   après coup : re-poser la question qu'on vient de trancher est ce qui a transformé une
#   fenêtre de quelques centaines de millisecondes en sept échecs.
socle_it_postgres_pret() {
  local conteneur="$1" plafond="${2:-180}" pret=0
  for _ in $(seq 1 "$plafond"); do
    if docker exec "$conteneur" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then
      pret=$((pret + 1))
      if [ "$pret" -ge 3 ]; then return 0; fi
    else
      pret=0
    fi
    sleep 1
  done
  socle_it_diagnostic_postgres "$conteneur" "$plafond"
  exit 1
}

# Le trap de sortie de l'appelant DÉTRUIT le conteneur : sans ces lignes, « voir docker
# logs » renvoie vers quelque chose qui n'existe plus, et l'échec reste opaque — il l'est
# resté six fois.
socle_it_diagnostic_postgres() {
  local conteneur="$1" plafond="$2" sortie code
  {
    echo "PostgreSQL jetable jamais prêt après ${plafond} s."
    # La boucle redirige stdout ET stderr vers /dev/null : une erreur de `docker exec` y est
    # invisible. C'est ce qui manquait pendant sept échecs. Même sonde que la boucle, en TCP
    # — une sonde de diagnostic qui n'interroge pas la même chose que la boucle rend un
    # verdict qui ne dit rien de l'échec.
    #
    # Le code de retour est capturé AVANT tout tube. La version précédente écrivait
    # `echo "code de retour : $?"` après un `| sed … || true`, donc affichait toujours 0 :
    # un diagnostic qui mentait, juste sous « jamais prêt ». Corrigé le 28/10/2026 en
    # extrayant cette garde.
    if sortie="$(docker exec "$conteneur" pg_isready -h 127.0.0.1 -U postgres 2>&1)"; then
      code=0
    else
      code=$?
    fi
    echo "dernier essai (même sonde que la boucle, en TCP), code de retour $code :"
    printf '%s\n' "$sortie" | sed 's/^/  /'
    echo "connexion directe : $(docker exec "$conteneur" \
      psql -U postgres -tAc 'select 1' 2>&1 | head -2 | tr '\n' ' ')"
    # La machine était-elle chargée ? C'est la seule question que les captures du 27/10
    # laissent ouverte : au repos, le conteneur est prêt en 1 à 3 s (mesuré six fois, avec
    # et sans fsync à l'initdb).
    echo "charge machine : $(cat /proc/loadavg)"
    echo "conteneurs actifs : $(docker ps -q | wc -l)"
    echo "disque : $(df -h / | tail -1)"
    echo "état du conteneur : $(docker inspect -f \
      '{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} err={{.State.Error}}' \
      "$conteneur" 2>&1)"
    echo "dernières lignes du conteneur :"
    docker logs --tail 20 "$conteneur" 2>&1 | sed 's/^/  /'
  } >&2
}
