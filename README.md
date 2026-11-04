# Miles

Back-office du projet *Terminal point relais* : administration d'un parc de terminaux
génériques — enrôlement, environnements, groupes, versions de paramétrage, référentiels.

## Trois produits, un seul dépôt

Découpage posé le 27 octobre 2026 (cadrage `terminal-pr`, *Découpage en trois produits*).
**Chaque produit a son répertoire, sa stack indépendante — front, back-office et base —
et son propre `dev-deploy.sh`.** Rien ne se déploie depuis la racine.

| Répertoire | Produit |
|---|---|
| [`portail/`](portail/) | Portail de configuration : workspaces, paramétrage versionné dans git, storages, sources de données |
| `enrolement/` | Service d'enrôlement : référentiel des devices, appariement des environnements *(à venir)* |
| `environnement/` | Back-office d'environnement : une stack et une base par environnement *(à venir)* |

Ce qui se partagera — compte d'amorçage à la première connexion, gestion OIDC — sera
extrait quand un deuxième produit en aura besoin, pas avant : un socle commun bâti sur un
seul usage devine les besoins du second au lieu de les servir.

## Travailler ici

`CLAUDE.md` porte les règles du dépôt et les commandes. Le backlog et le cadrage vivent
dans docflow, workspace `terminal-pr`.
