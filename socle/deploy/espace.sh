# shellcheck shell=bash
# L'espace disque de Docker : le mesurer, et le récupérer quand il manque.
#
# EXTRAIT de `gardes.sh` le 11/11/2026, et la raison est la doctrine du dépôt : on
# partage les gardes, pas la séquence. Cette garde-ci a maintenant DEUX usages — le
# déploiement (`gardes.sh`) et les campagnes d'intégration (`integration.sh`) —, et
# `gardes.sh` ne se source pas depuis une campagne : il porte vingt fonctions de
# déploiement qu'une campagne n'a pas à connaître, et qui lisent des variables qu'elle
# ne pose pas.
#
# POURQUOI les campagnes en avaient besoin : elles bâtissent des images, comme un
# déploiement. La garde posée le 11/11/2026 au matin ne couvrait que le déploiement, et
# c'est une campagne qui a porté le disque de `host-test-37` de 75 % à 87 % dans la
# même journée. Une garde qui protège une moitié des bâtisseurs protège mal.

# --- Espace disque AVANT la construction, et seulement quand il manque ------------------
# DEUXIÈME garde d'espace, et elle ne remplace pas la purge hebdomadaire de `gardes.sh` :
# les deux se complètent, et il faut les deux. (Elles étaient voisines jusqu'à
# l'extraction du 11/11/2026 ; la purge hebdomadaire est restée au déploiement, qui est
# le seul à avoir un témoin horodaté où noter son passage.)
#
# POURQUOI CELLE-CI EXISTE. La purge hebdomadaire est placée APRÈS le contrôle de santé,
# pour ne pas retarder la mise à disposition — c'est le bon choix en régime normal. Mais
# dans le cas précis pour lequel elle a été écrite, elle arrive trop tard : quand le disque
# est plein, c'est la CONSTRUCTION qui échoue, et elle passe avant. Mesuré le 11/11/2026 sur
# host-test-37 : 96 % d'occupation, 1,9 Go libres, 10,1 Go de cache de construction
# récupérable et AUCUN témoin de purge — exactement l'état de host-test-36 avant l'incident
# que la purge hebdomadaire cite. La garde qui devait l'empêcher ne pouvait pas le faire.
#
# CONDITIONNÉE AU BESOIN, PAS À LA FRÉQUENCE. Sur une machine saine, elle ne fait que lire
# `df` et rend la main : aucune minute ajoutée, donc aucune raison de la désactiver « le
# temps de » — c'est précisément ce qui avait rendu la purge inconditionnelle intenable.
# Elle ne tient aucun témoin : un disque court n'a pas de périodicité.
#
# Le code de retour ne fait JAMAIS échouer le déploiement, comme la purge hebdomadaire : si
# la purge ne récupère rien, c'est la construction qui dira que l'espace manque, et elle le
# dira mieux — avec le nom de la couche qui n'a pas pu s'écrire.
socle_espace_avant_construction() {
  local minimum_mo="$1" libre_mo apres_mo
  libre_mo="$(socle_espace_libre_mo)"
  ((libre_mo >= minimum_mo)) && return 0
  echo "AVERTISSEMENT : $libre_mo Mo libres pour Docker, sous le plancher de $minimum_mo Mo"
  {
    docker builder prune -f >/dev/null && docker image prune -f >/dev/null
    apres_mo="$(socle_espace_libre_mo)"
    echo "purge de nécessité : $((apres_mo - libre_mo)) Mo récupérés, $apres_mo Mo libres"
  } || echo "purge en échec (la construction dira si l'espace manque encore)"
}

socle_espace_libre_mo() {
  local cible kb
  # OÙ se mesure l'espace : là où les couches s'écrivent, et c'est Docker qui le dit. Sur
  # une machine en rootless ou dont le `data-root` est déplacé, `/var/lib/docker` n'existe
  # pas — et mesurer la racine annoncerait « au large » pendant que Docker étouffe.
  cible="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
  [[ -d "${cible:-}" ]] || cible=/var/lib/docker
  [[ -d "$cible" ]] || cible=/
  kb="$(df -k --output=avail "$cible" 2>/dev/null | tail -1 || true)"
  kb="${kb//[!0-9]/}"
  # NON MESURABLE : on rend un espace volontairement énorme, donc AUCUNE purge. Le repli
  # va dans ce sens et pas dans l'autre, et c'est une décision — relevée en éprouvant
  # cette garde le 11/11/2026, où « zéro libre par défaut » faisait purger à CHAQUE
  # déploiement sur toute machine dont le chemin diffère. C'est exactement ce qui avait
  # rendu la purge inconditionnelle intenable, et qui a motivé le témoin hebdomadaire.
  # Une construction à court d'espace, elle, le dira — et mieux : avec la couche fautive.
  [[ -n "$kb" ]] || { echo 99999999; return 0; }
  echo $((kb / 1024))
}

