# Ressources attribuées — Miles

Mémoire des machines de test et ressources mises à disposition (skill `test-machine-deployment`).
Ajouter une ligne à chaque attribution, la retirer quand la ressource est reprise.

| Alias SSH | Nom d'hôte réel | Usage | Depuis |
|---|---|---|---|
| `test1` | `host-test-36` (Debian 12, Docker 29.9, compose v5.6, utilisateur `root`) | tests d'intégration PostgreSQL, livraison par `dev-deploy.sh` | 2026-10-19 |

`host-test-23`, l'ancienne machine derrière `test1`, a été reprise le 2026-10-19.

Notes sur `test1`, relevées le 2026-10-19 :
- **Machine dédiée** à l'arrivée : seuls les services standard (alloy, browserless) y tournaient.
- **Ports** : Miles est publié sur **8080** (figé dans `/root/Miles/.env` au premier déploiement).
- **Broker MQTT** (Mosquitto 2.0.20) : port **1883** publié, sans accès anonyme.
  Seul le compte `miles-backend` existe ; les comptes des terminaux viendront de l'enrôlement.
- **Copie de déploiement** : `/root/Miles`, sur la branche `dev`. Annuaire du portail : `miles-miles`,
  `https://svc-miles-miles.yoops.org` → `100.74.129.165:8080`, joignable depuis le portail.
- **Compte d'amorçage** (créé par `dev-deploy.sh` le 2026-10-19) : utilisateur `admin`, e-mail
  `admin@miles.invalid`. Le mot de passe est dans `/root/Miles/.deploy/admin-password` (600), à lire
  sur la machine, jamais à recopier ailleurs. Pour rouvrir l'amorçage : retirer les trois entrées
  `MILES_ADMIN_*` de `/root/Miles/.env`, puis redémarrer le backend.
- **Relancer** : obtenir `PORTAL_TOKEN` (outil MCP `totp_code`, valable ~20 s), le passer sur stdin, puis
  `ssh test1 'IFS= read -r PORTAL_TOKEN; export PORTAL_TOKEN; cd /root/Miles && ./dev-deploy.sh'`.
- **git 2.39.5 sans durcissement HTTP/1.1** : `/etc/git/http2-github.inc` est absent. Un clone
  HTTPS de github.com peut échouer par intermittence en 401. Le remède est `harden-git-http.sh`
  (dépôt *ressources*), à poser au niveau système, pas dans notre script.
