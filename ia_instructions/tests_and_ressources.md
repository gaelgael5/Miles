# Ressources attribuées — Miles

Mémoire des machines de test et ressources mises à disposition (skill `test-machine-deployment`).
Ajouter une ligne à chaque attribution, la retirer quand la ressource est reprise.

| Alias SSH | Nom d'hôte réel | Usage | Depuis |
|---|---|---|---|
| `test1` | `host-test-37` (Debian 12, Docker 29.9.2, compose v5.6.1, utilisateur `root`) | tests d'intégration PostgreSQL, livraison par `dev-deploy.sh` | 2026-10-23 |

**L'alias `test1` a déjà désigné trois machines** : `host-test-23` (reprise le 2026-10-19),
`host-test-36` (reprise le 2026-10-23 vers 15:00, en pleine campagne d'intégration), puis
`host-test-37`. Vérifier le nom d'hôte réel derrière l'alias avant tout déploiement ou
diagnostic : l'adresse a changé à chaque fois (`100.74.129.165` → `100.74.9.236`).

Notes sur `test1` (`host-test-37`), relevées le 2026-10-23 :
- **Machine dédiée** : seuls les services standard y tournent (`devpod-alloy-agent`,
  `devpod-alloy-metrics`, `browserless-chromium` sur 3000, `buildx_buildkit`).
- **Ports** : le portail est publié sur **8080** et son broker MQTT sur **1883** ; le module
  d'enrôlement sur **8081**. Figés au premier déploiement dans le `.env` DU PRODUIT.
  **Deux stacks cohabitent** sur cette machine : projets compose `miles` et
  `miles-enrolement`, chacun avec sa base.
- **Copie de déploiement** : `/root/Miles`, branche `dev`, clonée en HTTPS anonyme
  (le dépôt est lisible sans clé : mesuré 10/10, pas besoin de `--bootstrap-deploy-key`).
- **Annuaire du portail** : `miles-miles`, `https://svc-miles-miles.yoops.org` →
  `100.74.9.236:8080`, et `miles-miles-enrolement`, `https://svc-miles-miles-enrolement.yoops.org`
  → `100.74.9.236:8081`. Les deux rendent **`joignable: true`** (vérifié au second passage de
  chacun — au premier, la stack n'écoute pas encore et l'avertissement est normal).
  Valeurs du premier passage : `EXPOSE_PORTAL_URL=https://dev.yoops.org`, `EXPOSE_WORKSPACE=miles`.
- **Comptes d'amorçage, un par produit et étanches** : utilisateur `admin` des deux côtés,
  mais deux comptes distincts. Mots de passe dans `/root/Miles/portail/.deploy/admin-password`
  et `/root/Miles/enrolement/.deploy/admin-password` (600), à lire sur la machine, jamais à
  recopier ailleurs. **Le chemin a changé le 27/10** : l'état est passé de la racine au
  répertoire du produit. Pour rouvrir l'amorçage d'un produit : retirer ses trois entrées
  `MILES_ADMIN_*` de SON `.env`, puis redémarrer son backend.
  Vérifié le 27/10 sur les stacks réelles : un jeton de session du portail est refusé par
  l'enrôlement (401) et réciproquement, et le mot de passe de l'un ne connecte pas à l'autre.
- **Base neuve** : les 22 migrations ont été jouées au premier déploiement. Aucun workspace
  ni contrat n'y est encore déclaré — les contrats de `host-test-36` ne sont pas repris.
- **Relancer** : obtenir `PORTAL_TOKEN` (outil MCP `totp_code`, valable ~30 s), le passer sur
  stdin — jamais en argument, `ps auxww` le verrait — puis, en nommant le PRODUIT :
  `ssh test1 'read -r PORTAL_TOKEN; export PORTAL_TOKEN; cd /root/Miles/<produit>; setsid nohup ./dev-deploy.sh > .deploy/livraison.log 2>&1 < /dev/null &'`.
  Le `&` ne doit porter que sur `setsid` : avec `&&` avant, c'est toute la liste qui part en
  tâche de fond, et le contrôle qui suit s'exécute depuis le mauvais répertoire.
  L'outil `totp_code` rend le MÊME code tant que la fenêtre court : si le `ttl_seconds` est
  bas, rappeler l'outil jusqu'au basculement plutôt que lancer avec 2 secondes devant soi.
- **Campagne d'intégration** : la lancer **détachée**
  (`setsid nohup ./scripts/run-integration-tests.sh > .deploy/integration-final.log 2>&1 &`).
  Lancée au premier plan, une chute de connexion la tue et le `ssh` rend `exit 0` — un vert
  trompeur qui ne vient pas de la campagne. Lire le verdict dans le journal, jamais le code retour.
- **Un déploiement pendant une campagne la casse** : `dev-deploy.sh` met à jour `/root/Miles`,
  que pytest lit — et le dépôt est COMMUN aux trois produits, donc livrer l'un casse la
  campagne de l'autre. Arrêter la campagne avant de livrer, puis la relancer.
- **git 2.39.5 sans durcissement HTTP/1.1** : `/etc/git/http2-github.inc` est absent. Un clone
  HTTPS de github.com peut échouer par intermittence en 401 (transport, pas droits ni quota).
  Le remède est `harden-git-http.sh` (dépôt *ressources*), à poser au niveau système, pas dans
  notre script. Mesuré bon 10/10 le 2026-10-23, mais le défaut est intermittent.
- **Purge disque** : `dev-deploy.sh` ne purge qu'**après** le contrôle de santé et au plus une
  fois par semaine. Un disque qui se remplit entre deux purges bloque donc la construction du
  déploiement qui aurait purgé — c'est arrivé sur `host-test-36` (95 %, 11 Go de cache).
  Remède durable côté image de machine de test (plafond du cache au niveau du démon).
