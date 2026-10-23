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
- **Ports** : Miles est publié sur **8080**, le broker MQTT sur **1883** (figés dans
  `/root/Miles/.env` au premier déploiement).
- **Copie de déploiement** : `/root/Miles`, branche `dev`, clonée en HTTPS anonyme
  (le dépôt est lisible sans clé : mesuré 10/10, pas besoin de `--bootstrap-deploy-key`).
- **Annuaire du portail** : `miles-miles`, `https://svc-miles-miles.yoops.org` →
  `100.74.9.236:8080`, et le portail rend **`joignable: true`** (vérifié au second passage).
  Valeurs du premier passage, prises de `.env.example` : `EXPOSE_PORTAL_URL=https://dev.yoops.org`,
  `EXPOSE_WORKSPACE=miles`.
- **Compte d'amorçage** (créé par `dev-deploy.sh` le 2026-10-23) : utilisateur `admin`.
  Le mot de passe est dans `/root/Miles/.deploy/admin-password` (600), à lire sur la machine,
  jamais à recopier ailleurs. Pour rouvrir l'amorçage : retirer les trois entrées
  `MILES_ADMIN_*` de `/root/Miles/.env`, puis redémarrer le backend.
- **Base neuve** : les 22 migrations ont été jouées au premier déploiement. Aucun workspace
  ni contrat n'y est encore déclaré — les contrats de `host-test-36` ne sont pas repris.
- **Relancer** : obtenir `PORTAL_TOKEN` (outil MCP `totp_code`, valable ~30 s), le passer sur
  stdin — jamais en argument, `ps auxww` le verrait — puis
  `ssh test1 'IFS= read -r PORTAL_TOKEN; export PORTAL_TOKEN; cd /root/Miles && ./dev-deploy.sh'`.
- **Campagne d'intégration** : la lancer **détachée**
  (`setsid nohup ./scripts/run-integration-tests.sh > .deploy/integration-final.log 2>&1 &`).
  Lancée au premier plan, une chute de connexion la tue et le `ssh` rend `exit 0` — un vert
  trompeur qui ne vient pas de la campagne. Lire le verdict dans le journal, jamais le code retour.
- **Un déploiement pendant une campagne la casse** : `dev-deploy.sh` fait `git reset` sur
  `/root/Miles`, que pytest lit. Arrêter la campagne avant de livrer, puis la relancer.
- **git 2.39.5 sans durcissement HTTP/1.1** : `/etc/git/http2-github.inc` est absent. Un clone
  HTTPS de github.com peut échouer par intermittence en 401 (transport, pas droits ni quota).
  Le remède est `harden-git-http.sh` (dépôt *ressources*), à poser au niveau système, pas dans
  notre script. Mesuré bon 10/10 le 2026-10-23, mais le défaut est intermittent.
- **Purge disque** : `dev-deploy.sh` ne purge qu'**après** le contrôle de santé et au plus une
  fois par semaine. Un disque qui se remplit entre deux purges bloque donc la construction du
  déploiement qui aurait purgé — c'est arrivé sur `host-test-36` (95 %, 11 Go de cache).
  Remède durable côté image de machine de test (plafond du cache au niveau du démon).
