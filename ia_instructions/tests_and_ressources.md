# Ressources attribuées — Miles

Mémoire des machines de test et ressources mises à disposition (skill `test-machine-deployment`).
Ajouter une ligne à chaque attribution, la retirer quand la ressource est reprise.

| Alias SSH | Nom d'hôte réel | Usage | Depuis |
|---|---|---|---|
| `test1` | `host-test-23` (Debian 12, Docker 29.8, compose v5.5, utilisateur `root`) | tests d'intégration PostgreSQL, livraison par `dev-deploy.sh` | 2026-10-18 |

Notes sur `test1`, relevées le 2026-10-18 :
- **Machine partagée** : elle héberge aussi `wsportal-dev`, `wsportal-dev-others` et `harpocrate`.
  Ne jamais agir hors du projet compose `miles`, sous peine d'arrêter les autres stacks.
- **Ports déjà pris** : 8000, 8080, 8081 et 8090 (entre autres). Miles y est publié sur **8180**
  (figé dans `/root/Miles/.env` depuis le premier déploiement, le 2026-10-19).
- **Copie de déploiement** : `/root/Miles`, sur la branche `dev`. Annuaire du portail : `miles-miles`,
  qui pointe sur `100.74.209.218:8180`.
- **Compte d'amorçage** (créé par `dev-deploy.sh` le 2026-10-19) : utilisateur `admin`, e-mail
  `admin@miles.invalid`. Le mot de passe est dans `/root/Miles/.deploy/admin-password` (600), à lire
  sur la machine, jamais à recopier ailleurs. Pour rouvrir l'amorçage : retirer les trois entrées
  `MILES_ADMIN_*` de `/root/Miles/.env`, puis redémarrer le backend.
- **Relancer** : obtenir `PORTAL_TOKEN` (outil MCP `totp_code`, valable ~20 s), le passer sur stdin, puis
  `ssh test1 'IFS= read -r PORTAL_TOKEN; export PORTAL_TOKEN; cd /root/Miles && ./dev-deploy.sh'`.
- **git 2.39.5 sans durcissement HTTP/1.1** : `/etc/git/http2-github.inc` est absent. Un clone
  HTTPS de github.com peut échouer par intermittence en 401. Le remède est `harden-git-http.sh`
  (dépôt *ressources*), à poser au niveau système, pas dans notre script.
