# shellcheck shell=bash
# Gardes des campagnes d'intégration, partagées par les trois produits.
#
# Même décision que pour le déploiement (Gael, 28/10/2026) : on partage les GARDES, pas la
# séquence. Ce qui suit encode une panne mesurée ; le reste de chaque
# `<produit>/scripts/run-integration-tests.sh` — ses ressources jetables, ses doublures de
# fournisseur, ses invocations de pytest — reste chez lui, parce que c'est là que les trois
# produits diffèrent vraiment : le portail lance une forge git et un courtier MQTT, les deux
# autres un fournisseur OIDC jetable.

socle_it_docker_present() {
  command -v docker >/dev/null \
    || { echo "docker introuvable : voir https://docs.docker.com/engine/install/" >&2; exit 1; }
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
