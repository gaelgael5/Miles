# Reprise de session — état au 27 octobre 2026

Point de reprise écrit à la demande de Gael, pour repartir d'un contexte propre.
**Le backlog docflow `terminal-pr` et le cadrage font foi, jamais ce fichier** : il dit où
on en est et ce qui n'est pas dans le code, rien de plus. Le relire puis interroger le
backlog.

## Où en est le produit

Le dépôt porte **trois produits** depuis le 27/10 (cadrage `terminal-pr`, article
*Découpage en trois produits*). Chacun aura son répertoire, sa stack — front, back-office,
base — et son propre `dev-deploy.sh`. Rien ne se déploie depuis la racine.

| Répertoire | Produit | État |
|---|---|---|
| `portail/` | Portail de configuration | livré, déployé sur test1 |
| `enrolement/` | Service d'enrôlement | **à construire** — ticket `1ea3f3de`, après le socle `5695664d` |
| `environnement/` | Back-office d'environnement | réduit à l'appariement d'abord — ticket `8c95ecc7` |

Livré dans `portail/` les 24-27/10, tout vert sur test1 :

- **Storages** — notion distincte de la source (Gael, 24/10). Déclaration dans git
  (`storages/<nom>.yaml`) : modèle, clé fonctionnelle, **index additionnels** nommés
  portant de 1 à 3 colonnes. Clé et colonnes se cochent dans un arbre du modèle, ouvert
  depuis un champ. Ticket `844f15ad`, en revue.
- **Sources de données** refondues en **conteneur d'entrées typées** (Gael, 25/10) :
  libellé, slug, *donnée cible* suffisent à enregistrer ; les entrées s'ajoutent ensuite,
  chacune avec son modèle source, sa chaîne, ses méthodes (élément seul, tableau de 200
  au plus, upload de fichier) et son lot d'écriture (100 par défaut).
- **Visualiseur Swagger** — sur chaque version de contrat, et sur l'API qu'une source
  promet, *dérivée* de sa déclaration (`sources/<nom>/openapi`).
- **Bouton de version grisé** quand il n'y a rien à figer, sur la réponse du serveur
  (`versions/freezable`) et non sur une règle recopiée.

## Ce qui tourne à l'instant

Une **campagne d'intégration** sur `91ab795`, lancée détachée sur test1. Lire le verdict :

```bash
ssh test1 'tail -3 /root/Miles/portail/.deploy/integration-final.log'
```

Verdict attendu : trois étapes (`300+ passed`, `1 passed`, `7 passed`). **Un journal de
77 octets n'est pas un succès** — voir la leçon ci-dessous.

## Ce qui attend Gael, et qui bloque

- **40 tickets en revue**, dont `66391afe` et `844f15ad`. Toute la chaîne d'ingestion
  (`4d4fdcef` → `d680e811` → `c705e801`) est derrière `66391afe`.
- Le ticket `c705e801` renvoie à un **« epic de la fabrique »** (génération du script
  d'initialisation, calcul de la stack) **qui n'existe pas dans le backlog**. Sans lui,
  le ticket consomme un schéma que personne ne produit. Signalé le 27/10.

## Ce qui est éligible, et par quoi commencer

- `5695664d` — **extraire le socle technique partagé** (amorçage, OIDC, sessions, cultures,
  secrets, journal d'events, runner de migrations) en paquet de code. **C'est la tête de
  file** : les deux coquilles et l'appariement l'attendent. Refactoring du portail livré,
  qui doit en sortir identique.
- `31025fe6` — modèles « Devices entrants » / « Devices sortants ».
- `449e1694` — famille « Sources » : le schéma de ce qu'une source reçoit.

**`6a0daab6` n'est PAS éligible**, contrairement à ce que montre son statut : il décrit un
protocole entre deux produits qui n'existent pas encore. Voir « Chaînage » ci-dessous.

## Cinq décisions prises par Gael le 27/10 — les questions sont closes

Les deux questions que ce fichier portait en suspens sont répondues, et trois autres ont été
posées et tranchées dans le même échange. **Le détail et sa raison sont dans les tickets**
(`5695664d`, `1ea3f3de`, `8c95ecc7`) ; ici, le résumé pour ne pas repartir à l'envers.

1. **On monte la coquille d'enrôlement complète**, et le produit d'environnement réduit à ce
   que l'appariement exige. Pas les deux coquilles complètes, pas le protocole seul.
2. **On extrait le socle maintenant**, puisque l'enrôlement est le deuxième usage de
   l'amorçage et de l'OIDC. L'option « dupliquer d'abord » est écartée.
3. **Le socle ne porte que du code, aucun SQL** : le schéma reste l'affaire de chaque produit.
   Conséquence assumée — la dérive de schéma entre produits est portée par la revue humaine,
   pas par un test. Les deux autres options (séquence propre au socle, SQL de référence
   recopié avec test de conformité) sont écartées : ne pas les rouvrir.
4. **Sessions étanches**, un cookie par produit, aucun secret de session commun — mais la
   reconnexion par OIDC est silencieuse quand le même connecteur est déclaré dans deux
   produits. C'est l'annuaire qui reconnaît, jamais notre cookie.
5. **Amorçage étanche** : un compte par produit, dans son propre `.env` et sa propre base.
   L'administrateur du portail n'ouvre rien sur l'enrôlement.

Les deux autres points que le cadrage désignait comme non délégués sont **déjà tranchés par
le cadrage** et embarqués comme contraintes : le journal d'events reste dans la base de son
produit (sinon la règle de transaction unique tombe), et le rapprochement d'identités ne
traverse pas les produits.

### Ce qui est mesuré, à ne pas re-découvrir

- **Socle : environ 3 400 lignes** — `auth/` 932, `oidc/` 1290, `secrets/` 724, `cultures/` 228,
  `events/` 312 (sauf `known.py`), `db/` 167.
- **Deux inversions de dépendance, et ce sont les seules.** `events/known.py` (52 lignes)
  importe 17 paquets du portail mais **reste dans le produit** — `events/model.py` reçoit déjà
  ses types par injection et `known.py` n'est lu que par `app.py`. Et `db/pool.py` doit recevoir
  ses paramètres au lieu d'importer `miles.config`.
- **`auth.gate` est importée par 37 modules d'API** : l'extraction touche leur ligne d'import,
  rien d'autre chez eux.
- **`additional_contexts` de compose fonctionne sur `test1`** — vérifié par un vrai build le
  27/10 (compose v5.6.1, Docker 29.9.2). Chaque produit garde `context: ./backend` et ajoute
  le socle en contexte additionnel ; jamais la racine du dépôt.

### Chaînage, et une limite de l'outil

`5695664d` (socle) → `1ea3f3de` (coquille enrôlement) et `8c95ecc7` (environnement réduit),
ces deux-là en parallèle → `6a0daab6` (échange de clés).

**Ce chaînage n'est pas déclaré en propriété sur `6a0daab6`** : `bloque_par` n'accepte qu'une
`story`, et les trois prérequis sont des `enabler`. Les enablers le déclarent dans leur corps.
Tant que ce n'est pas réglé, `6a0daab6` **paraît éligible alors qu'il ne l'est pas** — il décrit
un protocole entre deux produits qui n'existent pas encore dans le dépôt.

## Décisions renversées le 26/10 — ne pas repartir des anciennes

Le cadrage a changé d'avis, et c'est documenté comme tel :

| Dit par Gael le 24/10 | Tranché par le cadrage le 26/10 |
|---|---|
| tous les objets dans **une seule table**, tous environnements, bien partitionnée | **une table par storage**, dans le schéma de son domaine, dans la base de son environnement — `pudo.sites` |
| **table d'index générique** (une ligne par couple objet/propriété) | **colonnes dérivées par PostgreSQL** depuis le jsonb + index natifs déclarés |

Rien de livré n'est invalidé : la table d'objets n'a jamais été créée, faute de décision.
La déclaration d'un storage reste l'entrée du script engendré.

## Pièges éprouvés, à ne pas redécouvrir

Lire `LESSONS.md` — il porte les leçons du dépôt. Les plus coûteuses de cette session :

- **Un journal de campagne de 77 octets n'est pas un succès.** Sept échecs intermittents
  du 24 au 27/10 sur « PostgreSQL jetable jamais prêt », campagne jamais lancée. J'ai
  annoncé « 0 échec » trois fois sur un compteur qui ne pouvait pas être non nul avant la
  fin. **Cause toujours inconnue** : machine, disque, mémoire, image, réseau, contention
  et `initdb` lent sont tous écartés par mesure. Le script instrumente désormais l'échec
  (état et logs du conteneur, charge, sortie de `pg_isready`) — le prochain la donnera.
- **Changer la forme d'une charge utile, c'est la balayer dans TOUS les fichiers qui la
  construisent**, pas seulement le sien. Trois fois le même lot oublié au milieu de
  `test_storages_pg.py`, trois campagnes de vingt-cinq minutes pour le trouver.
- **`tests/integration/git_stack.py` câble ses services séparément d'`app.py`.** Un
  service ajouté à l'un et pas à l'autre fait tomber tous ses tests d'intégration.
- **Deux sites de déclaration pour une vue d'écran** : le routage et la liste du menu.
  Une vue absente de la liste donne un écran inatteignable, tout vert par ailleurs.
- **`MILES_SECRETS_KEY` ne se régénère jamais** : les secrets chiffrés en base
  deviendraient illisibles. `portail/dev-deploy.sh` porte une reprise qui *déplace*
  `.env`, `.env.bak` et `.deploy` au lieu de les recréer.

## Gestes du quotidien

```bash
cd portail/backend && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd portail/frontend && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
portail/dev-deploy.sh                      # livrer, PORTAL_TOKEN sur stdin, jamais en argv
portail/scripts/run-integration-tests.sh   # campagne, à lancer détachée
```

Le reste — machine de test, annuaire, compte d'amorçage, pièges de déploiement — est dans
`tests_and_ressources.md`, à côté.
