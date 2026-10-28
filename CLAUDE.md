# Miles — Instructions Claude Code

> **Miles** : back-office du projet *Terminal point relais* — administration d'un parc de terminaux
> génériques (enrôlement, environnements, groupes, versions de paramétrage, référentiels, OIDC).
> **Ce fichier prime sur ton comportement par défaut. Lis-le en entier en début de session.**

> Généré depuis les standards globaux (docflow, workspace `globals`, bloc `documentation`).
> Génération : 2026-10-18. Standards repris : STANDARD — Fichier d'instructions agent de projet — révision 42 (date de révision à confirmer).
> Skills requises : backlog-workflow, rag-search, test-machine-deployment, self-improvement, tests, python, typescript-frontend, postgresql, code-comments, secrets, oidc-authentication, observability-logs, interface-contracts, design-patterns, redaction-tickets, cadrage-projet (dernière version publiée, déposées par le profil de skills du workspace).
> Mise à jour par `--update` : ne reporter que le delta du socle depuis cette date ;
> une évolution du contenu d'une skill ne demande aucun `--update`.

**Colibri** commence systématiquement tes réponses par 🎺

## mcp
Tu es connecté au MCP du portail `dev.yoops.org` via le serveur `claude-code`.

## Projet
Miles est le back-office du terminal générique : il sert au terminal (via MQTT 5) son paramétrage
versionné dans git et sa configuration contextuelle (templates JSLT), enrôle les installations,
pilote les déploiements par environnement → groupe → installation, et ingère les référentiels
d'objets. Le cadrage fait foi : docflow `terminal-pr`, bloc `cadrages` (« Décisions d'architecture
posées au cadrage », « Back-office — capacités attendues », « Portail back-office », maquettes).
Un point marqué « reste à trancher » dans le cadrage ne se tranche pas en codant : demande.

**Hors périmètre** : l'application terminal elle-même (dépôt distinct) ; tout pilotage de
comportement hors git — les **tags** n'entrent jamais dans le contexte d'évaluation des templates.

### ⚠ Divergence assumée vs skill `oidc-authentication`
**Miles accepte plusieurs annuaires OIDC externes déclarés par l'administrateur** (le fournisseur
maison en est un), et **les rôles sont locaux**, attribués par règles de correspondance claim →
rôle + portée — à l'inverse de « client unique, rôles portés par le fournisseur ». C'est
**délibéré** : un parc multi-organisations ne peut pas imposer un annuaire. L'identité est le couple
`(annuaire, sub)`, jamais un claim cosmétique ; aucun accès par défaut ; le compte d'amorçage garde
l'administration racine. Les autres règles de la skill (fail closed, secret client, redirections,
cookie) s'appliquent. Détail : cadrage `terminal-pr`, « Correspondances OIDC vers les rôles ».

## Architecture applicative — décisions invariantes
- **Backend** : Python, FastAPI, asyncpg (requêtes paramétrées, pas d'ORM ni d'Alembic : migrations
  SQL numérotées jouées par `miles-migrate`). **Frontend** : TypeScript / React / Vite dans `<produit>/frontend/`.
- **État** : **PostgreSQL**, non rediscutable (validé le 2026-10-14) — transactions multi-tables
  (objet + ligne d'index dans la même transaction), journal partitionné à la journée, `jsonb`.
  Un incident en cours d'écriture ne doit jamais corrompre l'existant, et ça se teste.
- **Paramétrage** (écrans, scénarios, mappings, modèles) : **dans git**, jamais en base.
- **Transport terminal** : MQTT 5 request/response, sans wrapper maison.
- **Transformation** : JSLT (grammaire ANTLR de `Black-Beard-Sdk/jslt`) ; forme d'intégration
  côté Python *à confirmer*.

## Trois produits, un seul dépôt
Découpage posé par Gael le 27/10/2026, qui suit le cadrage « Découpage en trois produits ».
**Chaque produit a son répertoire, sa stack indépendante — front, back-office, base — et
son propre `dev-deploy.sh`.** Rien ne se déploie depuis la racine.

| Répertoire | Produit | État |
|---|---|---|
| `portail/` | Portail de configuration : workspaces, paramétrage, storages, sources | livré |
| `enrolement/` | Service d'enrôlement : référentiel des devices, appariement des environnements | coquille livrée, métier à venir |
| `environnement/` | Back-office d'environnement : une stack et une base par environnement | coquille livrée, **réduite à l'identité signée** ; métier à venir |

Ce qui se partage entre produits est **extrait au fur et à mesure**, quand un deuxième
produit en a besoin : on n'invente pas un socle commun avant d'avoir deux usages à servir.
C'est fait depuis le 27/10/2026 pour l'amorçage, l'OIDC, les sessions, les cultures, les
secrets, le journal d'events, les migrations, la journalisation et le contrôle de santé ;
depuis le 28/10/2026 pour les **clés et les appels signés** entre modules (`miles_socle.signing`),
dont les deux côtés doivent vérifier la même chaîne canonique au caractère près.

| Répertoire | Socle partagé | Consommé par |
|---|---|---|
| `socle/python` | paquet `miles_socle` — **aucun SQL**, le schéma reste l'affaire de chaque produit | `<produit>/backend`, chemin relatif dans `pyproject.toml` |
| `socle/web` | paquet `@miles/socle-web` — coquille front et écrans répliqués | `<produit>/frontend`, chemin relatif dans `package.json` |
| `socle/deploy` | `gardes.sh` et `integration.sh` — les gardes du déploiement et des campagnes | `<produit>/dev-deploy.sh` et `<produit>/scripts/`, par `source` |

`miles_socle.testing` est livré **dans** le paquet : chaque produit a sa suite et aucun ne
peut importer celle d'un autre. Il porte les doublures, la base jetable, la forme du `.env`
et le montage des services du socle sur une base réelle — le produit y injecte son
`build_app`, ses migrations et ses types d'events, jamais l'inverse. Et chaque produit porte
`tests/test_cablage.py`, qui **rougit en nommant** un service posé par `app.py` et câblé
dans aucun test d'intégration : c'est la garde qui remplace « penser à vérifier le harnais ».

### Ce qui n'est PAS partagé, et pourquoi — ne pas « finir le travail »

Décision de Gael du 28/10/2026 : **on partage les gardes, pas la séquence.** Une garde
encode une panne mesurée et se répare en un endroit ; une séquence est ce qui diffère
vraiment d'un produit à l'autre, et une erreur dedans ne doit casser qu'un produit — le
déploiement est la seule voie de livraison du projet.

| Reste au produit | Raison |
|---|---|
| la **séquence** de `dev-deploy.sh` et de `run-integration-tests.sh` | décision ci-dessus ; les étapes, leurs messages et leurs valeurs sont au produit |
| `docker-compose.yml` | c'est la définition de SA stack : base, volume, ports, nom de projet |
| `backend/Dockerfile`, `frontend/Dockerfile` | une image de base commune devient un prérequis de chaque déploiement, et le jour où elle manque les trois échouent sur un message qui ne parle pas d'elle |
| `frontend/vite.config.ts`, `eslint.config.js` | les partager fait résoudre `vite`, son greffon react ou les greffons eslint depuis le `node_modules` du socle. C'est la famille de pannes que `LESSONS.md` porte deux fois pour le front, et elle est invisible en local |
| `frontend/nginx.conf` | celui du portail diverge déjà de 34 lignes (surface MCP, éditeur JSLT) : un « commun » qui ne vaut que pour deux produits sur trois n'est pas une référence |
| `frontend/src/main.tsx`, `setupTests.ts` | le point d'entrée nomme l'`App` du produit, et les doublures de test sont celles de ses écrans |
| les **migrations** | le socle ne porte aucun SQL (décision du 27/10/2026) ; l'écart entre les trois schémas est tenu par la revue humaine |

Est partagé côté front, et c'est tout : `socle/web/tsconfig.base.json`, parce qu'`extends`
ne traverse aucune résolution de greffon — `strict` et `noUncheckedIndexedAccess` sont des
règles du dépôt, pas des préférences de produit.

**La frontière est tenue par un test, pas par une intention** : `tests/` à la racine lit les
imports (Python par `ast`, TypeScript par motif) **et les `source` des scripts shell**, et
refuse qu'un produit en atteigne un autre, ou que le socle atteigne un produit. À lancer
après tout déplacement de code entre les racines — et après tout nouveau genre de référence
inter-racines, qui doit y entrer le jour où on l'introduit.

## Commandes essentielles
Layout d'un produit : `backend/` (paquet Python, `migrations/NNNN_*.sql` immuables),
`frontend/` (Vite), `scripts/`, `docker-compose.yml`, `dev-deploy.sh`. Remplacer `<produit>`
par `portail`, `enrolement` ou `environnement` : les commandes sont les mêmes, les
environnements sont **indépendants** — un verrou et un `node_modules` par racine.
```bash
cd <produit>/backend && uv sync                         # installer
cd <produit>/backend && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src
cd <produit>/backend && uv run pytest -v                # unitaires (sans base)
<produit>/scripts/run-integration-tests.sh              # intégration PostgreSQL — machine de test
cd <produit>/frontend && npm ci && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
<produit>/dev-deploy.sh                                 # livrer (machine de test uniquement)
```
Les socles s'éprouvent seuls, et il faut le faire après les avoir touchés :
```bash
cd socle/python && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd socle/web    && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
cd tests        && uv run pytest -q                     # frontière socle / produits
```
Le portail est publié sur **8080**, le module d'enrôlement sur **8081**, le module
d'environnement sur **8082** : les trois stacks cohabitent sur la même machine de test.

## Backlog
Le backlog des tâches est dans le workspace docflow `terminal-pr`, bloc `backlog`. C'est la
source de vérité, jamais ta mémoire : le statut s'écrit à chaque tâche, à la prise et à la fin.
Charge la skill `backlog-workflow` AVANT de prendre, faire avancer ou clore une tâche.

## Recherche
Toute recherche d'information passe d'abord par le RAG (`rag__*` ; corpus `terminal-pr-docs`,
`globals-docs`), ensuite seulement par les outils locaux. Le RAG muet n'est pas une réponse : va
lire l'artefact réel. Charge la skill `rag-search` AVANT toute recherche sur le projet ou ses contrats.

## Quand charger une skill

Les skills ne sont PAS chargées d'office. Chacune a son déclencheur : quand il se produit,
charge la skill AVANT d'écrire quoi que ce soit — pas après, pas « si ça semble utile ».

| Tu t'apprêtes à… | Charge d'abord |
|---|---|
| prendre, faire avancer ou clore une tâche du backlog | la skill `backlog-workflow` |
| chercher une information sur le projet, ses voisins ou ses contrats | la skill `rag-search` |
| déployer ou livrer sur une machine de test, y tester ou y diagnostiquer, toucher au script de déploiement | la skill `test-machine-deployment` |
| corriger une erreur que l'utilisateur t'a signalée, ou une erreur qui se répète | la skill `self-improvement` |
| écrire ou modifier du code de production ou de test, corriger un bug, déclarer « terminé » | la skill `tests` |
| écrire ou modifier du code, quel que soit le fichier | la skill `code-comments` |
| écrire, modifier ou relire un fichier `.py`, ou toucher `pyproject.toml` | la skill `python` |
| écrire, modifier ou relire un fichier `.ts` / `.tsx` sous un `frontend/` | la skill `typescript-frontend` |
| écrire une migration, une requête SQL ou du code d'accès aux données | la skill `postgresql` |
| ajouter, lire, injecter ou journaliser un secret ; toucher Dockerfile, compose, `.env` ; committer | la skill `secrets` |
| toucher au login, aux connecteurs OIDC, aux rôles, aux routes protégées, au cookie de session | la skill `oidc-authentication` (voir la divergence ci-dessus) |
| ajouter ou modifier un appel de journalisation | la skill `observability-logs` |
| ajouter ou modifier une route HTTP, un topic MQTT, un schéma d'event, un `*.openapi.json`, un outil MCP | la skill `interface-contracts` |
| introduire une abstraction, une interface, une fabrique ou un bus d'événements | la skill `design-patterns` |
| créer ou compléter des tickets dans le backlog | la skill `redaction-tickets` |
| démarrer un sujet que le cadrage `terminal-pr` n'instruit pas | la skill `cadrage-projet` |

Une skill introuvable se **signale** ; on ne devine pas ce qu'elle contenait (voir « Repli »).

## Repli — skill absente
Une skill de la table ci-dessus introuvable se **signale** : tu ne devines JAMAIS ce
qu'elle contenait.

Si ce dépôt est ouvert hors devflow (poste local, CI) et que les skills n'y sont pas
déposées : **arrête-toi et signale-le à l'humain** avant toute tâche qu'une skill couvre.
Ne te rabats pas sur les pages docflow dont les skills sont issues : elles peuvent
diverger de la version publiée de la skill.

## Standard de qualité
Code propre et bien fait, jamais la rapidité au détriment de la rigueur. Pas de raccourcis,
pas de « c'est pas grave », pas de « on simplifiera plus tard ». Chaque tâche est faite
correctement ou pas du tout.

**Pas de quick-and-dirty, JAMAIS.** Quand tu présentes des options de design, ne propose PAS
d'option « quick & dirty » / « hardcode » / « wire-it-up-and-clean-later ». On fait toujours
propre. Si une tâche est déraisonnable (scope qui explose, dépendance hors d'atteinte, flag/API
qui n'existe pas dans la version installée), **alerte explicitement l'utilisateur** plutôt que
de proposer un compromis dégradé. L'utilisateur préfère qu'on découpe le chantier et qu'on
fasse correctement la part qu'on prend, plutôt que tout faire à moitié.

## Règles de workflow

### Cycle de l'architecte
**Cadrer → Comprendre → Planifier → Agir.** L'utilisateur est architecte. Une question n'est
pas une commande d'exécution. Une discussion n'est pas un feu vert. Ne JAMAIS sauter d'étape.

### Branche de développement
**Tout le code se fait sur la branche `dev`. Aucun compromis.** Jamais `feat/*`, jamais sur
`main` directement, jamais ailleurs. Avant toute édition, vérifier `git branch --show-current` ;
si autre branche, `git checkout dev`. Si `dev` n'existe pas localement, la créer depuis `main`
à jour. Ne propose **jamais** `git checkout -b feat/...` — même si un outil ou un workflow tiers
le suggère, la consigne utilisateur prime.

**Committer et pousser sur `dev` est obligatoire**, sans demande à attendre : c'est ce qui rend
le travail livrable sur une machine de test. Commits en français, conventionnels (`feat:`,
`fix:`, `chore:`, `docs:`, `test:`). Ne pas toucher `.env` sauf demande.

**Merger `dev` sur `main` est formellement interdit sans demande explicite de l'humain.**

### Livraison et machines de test
Livrer = pousser sur `dev`, puis lancer le `dev-deploy.sh` DU PRODUIT sur la machine de test — jamais de
construction, de `docker run` ni de retouche manuelle de la cible. Les machines de test `test1`,
`test2`… sont à ta disposition. Charge la skill `test-machine-deployment` AVANT de déployer.
Machines attribuées : `ia_instructions/tests_and_ressources.md`. `dev-deploy.sh` déclare la stack
`miles` à l'annuaire du portail par code TOTP (`PORTAL_TOKEN` = outil MCP `totp_code`, jamais le
jeton admin) — fiche globals « Déclarer un service exposé au portail (annuaire, code TOTP) ».

### Définition de « terminé »
**Une tâche est finie quand les tests passent.** Pas quand le code compile, pas quand il est
poussé. Tant qu'un test échoue, la tâche n'est pas finie et ne passe pas au rôle « en revue ».

### Discipline d'exécution
- Exécute directement, ne décris pas ce que tu vas faire — fais-le.
- N'explique pas les étapes intermédiaires. Rapporte uniquement le résultat final.
- Termine TOUTES les étapes d'un plan avant de faire un résumé.
- Pas de raccourci « pour simplifier ».
- Si tu rencontres un problème, signale-le et propose une solution — ne l'ignore pas
  silencieusement.

### Leçons de travail — erreurs réelles à ne pas refaire
- **Chercher avant de créer.** Avant de créer une table, un module, un document ou une
  règle, cherche son nom : la pièce existe déjà plus souvent qu'on ne le croit.
- **Interroger le système plutôt que déduire de la doc.** La documentation dit ce qui est
  illustré, pas ce qui est permis. Quand un accès existe (bac à sable, `--help`, requête
  réelle), interroge-le. Ce qui se vérifie ne se déduit pas ; une déduction s'annonce
  comme telle.
- **Exclure les zones littérales des transformations.** Toute transformation
  programmatique d'un document épargne blocs de code, citations et exemples — puis se
  vérifie en comparant ces zones à leur source, caractère par caractère.
- **Ne lancer que les outils déclarés.** Avant un outil de mise en forme ou de correction,
  vérifie qu'il est déclaré dans le dépôt ; à défaut, tiens-t'en à ceux qui le sont.
- **Vérifier la cible avant d'agir.** Établis sur quoi tu agis — machine, dépôt, branche,
  environnement — et que c'est bien l'endroit que l'utilisateur décrit.
- **Un symptôme à causes multiples ne désigne pas sa cause.** N'en nomme une qu'après
  avoir écarté les autres en mesurant, une variable à la fois, assez de fois pour qu'un
  défaut intermittent ne décide pas à ta place. Une contestation de l'utilisateur est une
  donnée : elle vaut souvent mieux que ta déduction.
- **Relire après écriture.** Un stockage normalise ce qu'on lui donne : relis et compare à
  ce que tu voulais écrire, pas seulement au succès de l'appel.
- **Vérifier le résultat, jamais le code de retour.** Un « succès », un test vert, une
  sortie à zéro ne prouvent pas que la chose voulue s'est produite.

## Auto-amélioration
Une erreur corrigée devient une leçon dans `LESSONS.md`. Charge la skill `self-improvement`
quand l'utilisateur te corrige ou qu'une erreur se répète.

## Sécurité (non négociable)
- Aucun secret en argument de construction, variable d'image, couche, log, colonne claire ni
  dans le dépôt (`.mcp.json` porte un jeton : il est exclu par `.git/info/exclude`, ne le committe jamais).
- **Fail closed** : route sans autorisation explicite refusée ; claim de groupe absent = refus.
- Entrées utilisateur validées avant tout usage en chemin, identifiant, nom d'hôte ou URL de dépôt.
- Gardes propres à Miles, **chacune testée** : l'écran d'amorçage se referme définitivement dès
  qu'un administrateur existe ; une liaison d'identités exige deux déclarations ; le secret d'un
  connecteur OIDC ou d'un dépôt n'est jamais restitué ; seuls les profils d'écriture JSLT admis passent.

## Outils de l'agent
- Doc d'une bibliothèque : Context7, avant d'écrire du code qui l'utilise.
- CLI externe : `--help` d'abord, c'est le binaire installé qui fait foi.
- Navigation sémantique : pas de Serena ici — `grep` structuré avant un refactor.
- Méthodes : skills `writing-plans`, `executing-plans`, `test-driven-development`, `verification-before-completion`.
- Revue (>3 fichiers ou >100 lignes) : `/code-review` ; commit à la main, au format ci-dessus.

## Notifications de capacités
Quand tu invoques une capacité outillée (skill, commande, extension), affiche systématiquement
un marqueur **avant** d'exécuter :
> **`🟢 SKILL`** → _nom_ — raison en une phrase

## Vérification avant « terminé »
1. Style, types et construction passent (back et front).
2. Le cas nominal est testé.
3. Les imports ajoutés existent réellement.
4. Aucune régression sur les fichiers touchés.
5. Parts de checklist chargées et cochées : `tests`, `python`, `typescript-frontend`,
   `postgresql`, `oidc-authentication`, `interface-contracts` — selon les fichiers touchés.
6. Aucun secret dans le diff, relu sous cet angle (skill `secrets`).
7. Les tests passent là où ils sont le plus révélateurs — sur une machine de test dès qu'elle
   peut révéler davantage que le local.
