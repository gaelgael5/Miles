# Reprise de session — état au 28 octobre 2026

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
| `portail/` | Portail de configuration | livré, déployé sur test1, **port 8080** |
| `enrolement/` | Service d'enrôlement | coquille le 27/10 ; **sert le protocole d'appariement** depuis le 28/10 (ticket `6a0daab6`), **port 8081**. Le parc des devices reste à faire |
| `environnement/` | Back-office d'environnement | coquille le 28/10 ; **frappe, confirme et range la clé de son pair** depuis le 28/10, **port 8082**. Le métier reste à faire |

**Trois socles partagés**, et c'est là que vit le code commun : `socle/python` (paquet
`miles_socle`), `socle/web` (paquet `@miles/socle-web`) et `socle/deploy` (les gardes des
scripts). Le socle porte les **requêtes** de ses propres tables mais **aucune migration** :
le schéma reste à chaque produit, relu produit par produit. La frontière entre les racines
est tenue par `tests/` — 22 tests, Python par `ast`, TypeScript par motif et shell par ses
`source`. À lancer après tout déplacement de code entre racines.

## Ce qui vient d'être livré — l'appariement (28/10, ticket `6a0daab6`)

Un module d'environnement et le module d'enrôlement s'apparient, et à l'issue **chacun
détient sa clé privée et la clé publique de l'autre**. Le contrat est publié dans docflow :
*Appariement et appels signés entre modules Miles*, sous « Contrats d'interface de Miles ».

- L'environnement **frappe** (`POST /api/peer/pairing/request`) et dépose sa clé publique ;
  un administrateur voit la demande côté enrôlement, en lit le **code TOTP** et le recopie
  dans l'environnement ; la **confirmation** (`POST /api/peer/pairing/confirm`) rend la clé
  publique de l'enrôlement.
- **Trois sources de confiance distinctes** : la demande est signée par la clé qu'elle
  dépose (possession, pas identité) ; la confirmation par la clé déjà déposée **plus** le
  code (un humain l'a voulu) ; les appels ordinaires par la clé d'un pair apparié.
- Le secret du code **vit en base**, jamais en mémoire de processus : l'humain lit le code
  sur une instance et le colle vers une autre.
- **Tous les refus sont opaques et identiques**, sauf la dérive d'horloge, qui nomme sa
  cause et n'offre aucun oracle. La raison précise est au journal.
- Passés au socle, deuxième usage obligeant : l'**identité de module**
  (`signing/identity.py`) et le **contrat d'appel** (`signing/protocol.py`). Les chemins
  entrent dans la chaîne signée — deux constantes de même valeur auraient divergé.
- Le **TOTP reste dans l'enrôlement** : un seul usage à ce jour, donc pas d'extraction.
- Vérifié sur test1 entre les deux stacks vivantes : appariement réel, code faux refusé
  sans détruire la demande, code rejoué refusé, appel signé accepté dans les deux sens de
  vérification, et trois refus (clé inconnue, aucune signature, origine jamais appariée)
  tous identiques côté réponse et distingués au journal.

**Pièges de la machine de test, mesurés** :

- le **nom court de l'hôte ne se résout pas** dans un conteneur, et le domaine public des
  modules est derrière le **SSO du portail** (403 pour une machine, écran de connexion
  pour un navigateur). Pour un essai entre stacks, passer par la passerelle Docker
  (`http://172.24.0.1:<port>` depuis un conteneur, `172.17.0.1` depuis browserless) ;
- le **cookie de session est `Secure`** en production : un navigateur refuse de le garder
  en clair, donc on ne peut pas ouvrir une session Miles en HTTP depuis browserless. Pour
  éprouver un écran dans un VRAI navigateur, monter le bundle servi et **intercepter
  `fetch`** avant le démarrage (`page.evaluateOnNewDocument`). C'est ce qui a trouvé un
  gabarit i18n non interpolé que jsdom laissait passer.

## Et les deux écrans de l'appariement (28/10, tickets `ce66f5bb` et `29d05f91`)

- Côté **enrôlement** : les demandes en attente, le code qui se renouvelle, le refus. Le
  geste d'acceptation EST la transmission du code — seul un administrateur voit cet écran,
  et le protocole n'a pas d'autre porte. Le code n'a qu'une sortie : le presse-papiers.
- Côté **environnement** : les quatre états du ticket, plus un cinquième — **pair
  injoignable** —, parce que confondre « ne répond pas » avec « a refusé » ferait
  recommencer une demande que quelqu'un est en train d'accepter.
- Le **nom déclaré** arrive avec eux. Il n'identifie RIEN : deux demandes peuvent porter
  le même, seule l'URL les distingue. Nettoyé de ses caractères de contrôle, jamais
  dépouillé de ce qui ressemble à du balisage — l'échappement appartient à l'affichage.
- Le **nombre de devices** est rendu `null` et affiché « — » : le référentiel n'existe pas
  encore, et zéro se lirait « aucun device ».

**Trois défauts trouvés par la campagne, qu'aucun test local ne pouvait voir** : le code
collé n'était nettoyé que par le navigateur ; un nom trop long était refusé sur « corps
invalide » au lieu de nommer le champ ; et un `401` de la route d'état — le pair ne
détient plus ni demande ni appariement — était lu comme une panne de réseau, si bien que
l'écran aurait dit « injoignable » là où un humain venait de refuser.

## Et le référentiel des environnements (28/10, ticket `2ea50d40`)

Le module d'enrôlement ne savait pas **nommer** un environnement : il connaissait des
appariements, repérés par une URL et portant un nom déclaré qu'un tiers non authentifié
avait écrit. « Affecter un device à un environnement » n'avait donc pas de sujet. Deux
tickets déjà écrits — `a4f05302` et `44ea3db7` — supposaient cette liste sans que rien ne
la crée.

- Un environnement porte un **libellé** (ce qui se lit) et un **slug** (ce qui s'écrit),
  tous deux **renommables** : rien de durable ne le désigne par son slug, l'adresse
  d'enrôlement devant le désigner par un identifiant opaque et régénérable. L'unicité se
  revérifie donc à chaque renommage.
- Le slug **suit le libellé tant que personne n'y a touché**, et cesse de le suivre dès
  qu'il est édité. Sans cette règle, corriger le libellé après avoir choisi son slug
  efface le choix sans rien dire. La dérivation vit au FRONT : ce qui arrive au serveur
  est un choix, qu'il valide sans jamais le réécrire.
- Une dérivation qui ne donne rien laisse le champ **vide** — aucun `environnement-1`
  inventé : un slug que personne n'a choisi est un slug que personne ne reconnaît.
- L'unicité est tenue par la **base** : pas de `SELECT` avant l'`INSERT`, la violation est
  traduite en 409. Éprouvé par trois créations concurrentes du même slug.
- La colonne `environment_peer.environment_id` est **créée sans être remplie** : c'est le
  geste de désignation (`bf2115cd`) qui la remplira. Elle est là parce que, sans elle, le
  référentiel ne peut pas répondre à « puis-je supprimer ? ». `ON DELETE RESTRICT`, et
  `UNIQUE` : un environnement porte AU PLUS un appariement.
- **Mesuré** : retirer la vérification applicative de suppression ne fait rougir aucun
  test — c'est la clé étrangère qui tient. Le code le dit, pour qu'on ne la croie pas
  porteuse de la garde.
- La suppression ne regarde PAS les devices : le référentiel des devices n'existe pas, et
  compter zéro serait mentir. Le refus se dédoublera le jour où il existera.

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

## Et la désignation de l'environnement (28/10, ticket `bf2115cd`)

Ce qui relie les deux moitiés : une stack qui frappe, et un environnement du référentiel.

- **Révéler le code EST le geste d'acceptation** (décidé au ticket `ce66f5bb`). Désigner
  l'environnement en devient donc une CONDITION de l'acceptation, pas une formalité qui
  la suit. Sans désignation, la route du code rend 409 `environnement_non_designe`, et
  l'écran écrit pourquoi — un bouton grisé muet fait chercher la panne ailleurs.
- La désignation vit sur la **demande** (`pairing_request.environment_id`), pas seulement
  sur l'appariement : elle doit exister avant que l'appariement ne soit conclu.
- Elle est **héritée** de l'appariement déjà conclu sous la même origine, au moment où la
  demande s'ouvre. Une seule ligne de SQL, et elle fait tenir deux règles sans cas
  particulier ailleurs : une stack qui refrappe ne fait pas perdre le choix à l'humain, et
  une stack qui tourne ses clés réapparie le MÊME environnement. Déplacer un appariement
  conclu reste inexprimable — ce geste s'appelle révoquer puis réapparier.
- **Pas d'UNIQUE sur la demande**, à la différence de l'appariement : deux demandes
  peuvent viser le même environnement, parce qu'aucune ne le CONSOMME tant qu'elle n'est
  pas conclue (refusée ou expirée, elle le libère). La course se tranche à la
  confirmation, et le refus arrive AVANT que le code ne soit brûlé — un code brûlé sur un
  refus obligerait l'environnement à refrapper pour un code qu'il ne pourrait plus faire
  accepter.
- Ce refus-là est **dit** à l'environnement (409 `environnement_indisponible`), par
  exception à l'opacité des refus d'appariement — même raison que la dérive d'horloge :
  on ne l'atteint qu'après avoir passé la signature ET présenté un code valide.
- Le **raccourci de création** depuis l'écran d'appariement emploie le MÊME formulaire que
  le référentiel, et rattache la demande aussitôt. Un environnement créé puis laissé non
  désigné ferait croire le geste terminé.
- Les **appariements hérités** (sans environnement) sont signalés « à rattacher » et se
  rattachent sans toucher aux clés. Le rattachement n'est possible qu'une fois :
  `WHERE environment_id IS NULL` rend le déplacement inexprimable en SQL.
- Le référentiel refuse désormais de **supprimer un environnement désigné** par une
  demande en attente (409 `environnement_designe`, distinct de `environnement_apparie` :
  les deux appellent des gestes différents).

## Et la révocation (29/10, ticket `d5ffeb33`)

Le geste inverse de l'appariement, et il n'en est pas le symétrique.

- **Révoquer SUPPRIME la ligne** de `environment_peer`, clé publique du pair comprise. Pas
  de colonne `revoked`, pas de drapeau : le critère 8 demande des clés détruites, et un
  drapeau laisse la clé à portée du premier filtre oublié — un oubli invisible en test.
- Une **pierre tombale** (`revoked_pairing`) est posée dans la même transaction. Elle ne
  change AUCUNE réponse : un appel signé d'une origine révoquée reçoit le même 401 opaque
  qu'une origine inconnue, mot pour mot, et c'est ce qui l'empêche d'être un oracle. Elle
  ne change que le mot au JOURNAL — `origine_revoquee` au lieu d'`origine_inconnue`. Sans
  lui, le diagnostic cherche une clé perdue alors qu'un humain a décidé.
- Elle **part au ré-appariement** : la garder ferait dater une révocation ultérieure de la
  précédente. L'historique reste entier dans les events, qui ne s'écrasent pas.
- L'**environnement reste au référentiel** et redevient libre immédiatement : révoquer
  porte sur l'appariement, pas sur l'environnement.
- L'event `pairing.revoked` porte son auteur, l'environnement quitté avec ses deux noms du
  moment, et `devices_released` à **NUL — jamais 0** : le référentiel des devices n'existe
  pas, et un zéro serait indiscernable dans un an d'un vrai « aucun device libéré ».
- Côté **module d'environnement**, l'état « apparié » ne se lit plus localement : il est
  DEMANDÉ au pair à l'affichage, par l'échange de vivacité déjà en place (aucune route
  nouvelle). Un 401 portant un code de refus de route de pair donne l'état
  `refuse_par_le_pair` ; un 401 nu — celui du portillon — ne dit rien et donne
  `pair_injoignable`. L'appariement reste AFFICHÉ sous l'avertissement : on ne détruit
  rien sur la foi d'une réponse distante.
- **Ce qui n'est pas éprouvé, et qui doit être redit** : les critères 2, 3 et 5 portent sur
  des devices remis en attente d'affectation. Le référentiel des devices n'existe pas, donc
  rien de ces trois-là n'est vérifiable aujourd'hui. C'est écrit dans le ticket.

## Ce qui vient d'être livré — le socle partagé

**Ticket `5695664d`, en revue.** Le socle technique est sorti du portail et vit dans
`socle/python` (paquet `miles_socle`) : `auth`, `oidc`, `secrets`, `cultures`, `events`
et `db`, environ 3 400 lignes, **aucun SQL**. Le portail en sort identique.

- Les deux inversions prévues étaient bien les seules. `events/known.py` est remonté en
  `miles/event_types.py` côté produit ; `db/pool.py` déclare un `Protocol` au lieu
  d'importer `miles.config`.
- `tests/architecture` tient la frontière : il lit les imports à l'`ast` sans charger le
  code, et **trois de ses six tests introduisent la faute pour de vrai** — un test de
  frontière qui ne peut pas échouer ne tient rien.
- Le socle entre dans l'image par un contexte de build additionnel. **L'image bâtit dans
  `/src/portail/backend`, pas dans `/app`** : uv refuse de normaliser un chemin qui remonte
  au-dessus de son répertoire de base, et `/app/../../socle/python` sortait de la racine.
  Ne pas « simplifier » en revenant à `/app`.
- Vérifié : 802 unitaires avant, **657 portail + 145 socle = 802** après ; campagne
  **301 + 1 + 7 = 309, zéro échec** ; 25 migrations inchangées ; image inspectée, aucune
  trace des autres produits.

### Puis le socle web, et le deuxième produit — 27/10 au soir

Monter l'enrôlement a révélé que `5695664d` n'avait extrait que le Python. **Arbitré par
Gael : on factorise maintenant**, même règle que pour le socle Python — deux usages.

- `socle/web` (paquet `@miles/socle-web`) porte la coquille front et les écrans que le
  cadrage déclare « répliqués dans les trois produits » : amorçage, connexion, connecteurs
  OIDC, cultures, secrets, profil, santé. **35 fichiers déplacés par `git mv`, aucun test
  réécrit** ; 41 fichiers et 255 tests au total, comme avant déplacement.
- Trois pièges qui ne se devinent pas, et qui sont commentés sur place : l'i18n
  s'initialise par **appel** et non par effet de bord d'import (le socle ne connaît pas les
  libellés de son consommateur, et les espaces `app` et `profile` sont partagés, d'où une
  fusion en profondeur) ; `resolve.dedupe` est **obligatoire** côté produit, sinon la page
  embarque deux React ; l'image du front installe le socle avec **son** verrou, la
  résolution de modules remontant depuis le fichier qui importe.
- Quatre modules du portail étaient du socle déguisé et sont partis aussi :
  journalisation, sonde de santé et sa route, `cli_admin`. Le CLI de migration s'est coupé
  en deux — mécanique au socle, configuration au produit. `miles_socle.testing` porte les
  doublures d'accès à la base, livrées DANS le paquet, chaque produit ayant sa suite.
- **`enrolement/` est monté** : sa base, ses 7 migrations repartant de `0001`, son back qui
  consomme le socle, son front, sa stack, son `dev-deploy.sh`. Il démarre, se déploie et
  se connecte — et rien de plus.

### Puis le troisième produit — 28/10

**Ticket `8c95ecc7`, en revue.** `environnement/` est monté, réduit à ce que l'appariement
exige : sa base (8 migrations depuis `0001`), son back, son front, sa stack, son
`dev-deploy.sh`, publié sur **8082**. Le métier d'environnement — objets, entrées, sorties,
site, APIs, paramétrage servi — n'y est pas, et c'est voulu : plusieurs de ses questions
sont **ouvertes au cadrage** (où vit la base d'un environnement, le mécanisme de vague, le
registre des stacks déployées), et les trancher en codant est précisément ce que le projet
s'interdit.

Ce que le produit détient, et qui est nouveau dans le dépôt :

- **une paire de clés Ed25519 engendrée chez lui**, sa clé privée rangée comme secret du
  produit (chiffrée par `MILES_SECRETS_KEY`, usage déclaré pour que la base refuse de la
  supprimer), et la clé publique du module d'enrôlement apparié ;
- **`miles_socle.signing`**, troisième brique du socle : engendrer et relire une paire,
  signer et vérifier un appel. Les deux côtés du protocole doivent vérifier la MÊME chaîne
  canonique au caractère près — deux copies divergeraient, et le symptôme serait un 401 que
  personne n'attribue ;
- **une route authentifiée par signature et non par session**, `POST /api/peer/ping`. Le
  portillon du socle laisse passer les chemins qu'un produit déclare comme tels, défaut
  l'ensemble vide, et le produit **dérive cette liste du routeur** qui porte les routes :
  un chemin ouvert à côté de sa vérification n'est pas exprimable.

**La signature lie le contenu de l'appel, pas son instant.** C'est écrit dans le code et
ce n'est pas un oubli : l'horodatage, le nonce et l'anti-rejeu sont l'objet du ticket
*Enveloppe d'appel à usage unique*, et la version figure déjà dans la chaîne signée pour
que rien d'ancien ne reste acceptable ce jour-là.

Mesuré sur test1 le 28/10 : identité **identique après redéploiement** (même clé, même
`created_at`, même chiffré en base), les **deux sens** de l'échange signé acceptés avant
comme après, une clé inconnue refusée et journalisée avec son origine, les trois jetons de
session étanches deux à deux, l'image sans aucune trace des autres produits.

### Puis la construction des socles — 28/10, décidée par Gael

« On continue sur la construction des socles », en **trois tranches**, dans cet ordre.
Mesuré d'abord : entre les deux coquilles seules, 754 lignes d'échafaudage de test dont 80
divergentes, 530 lignes d'infra quasi identiques, 200 lignes à **zéro divergence**.

| Ticket | Tranche | État |
|---|---|---|
| `cadc9f40` | l'échafaudage de **test** | **livré le 28/10**, en revue |
| `710ab8a2` | le **câblage** de `app.py` et la **configuration** | à faire |
| `ef9a32ca` | l'**infra** : les gardes du déploiement et des campagnes | **livré le 28/10**, en revue |

**Tranche 1, livrée.** `miles_socle.testing` est devenu un paquet : doublures, base jetable,
forme du `.env`, fixtures unitaires, et le montage des sept services du socle sur une base
réelle. Le produit y injecte son `build_app`, ses migrations et ses types d'events — le
socle ne l'importe jamais. 175 lignes de moins dans les produits ; les harnais des coquilles
passent de 151 à 66 et de 172 à 104.

Mais le gain de lignes n'est pas le motif. **`tests/test_cablage.py`, dans chaque produit,
rougit en NOMMANT un service posé par `app.py` et câblé dans aucun test d'intégration** —
la panne que `LESSONS.md` portait deux fois, 22 puis 15 tests rouges. Lue par `ast`, donc
unitaire et lancée à chaque fois. La liste des absents admis est fermée par défaut, et sa
seule entrée est une trouvaille : la suite d'intégration du portail ne câble jamais sa
sonde de santé.

Le portail garde son montage minimal et son câblage par test : pré-câbler les sept services
changerait ce que quinze fichiers observent, et **un refactoring ne réécrit pas les tests**.

**Tranche 2, livrée.** `wire_socle_services` câble les sept services du socle, et c'est la
MÊME fonction qu'appellent la production et le harnais de test : les oublier n'est plus
exprimable. `miles_socle.settings` porte la base de configuration ; le produit n'ajoute que
ses champs propres et le répertoire de ses migrations, le seul que le socle ne peut pas
connaître. `config.py` tombe de 84 à 28 lignes dans les coquilles, de 93 à 49 au portail.

**Tranche 3, livrée.** Gael a tranché : **on partage les gardes, pas la séquence.**
`socle/deploy/gardes.sh` porte les douze gardes du déploiement et
`socle/deploy/integration.sh` celle du PostgreSQL jetable ; les trois `dev-deploy.sh`
passent de 1022 lignes à 455, et les onze étapes du portail sont identiques mot pour mot.
Une erreur dans une séquence ne casse donc qu'un produit — le déploiement est la seule voie
de livraison du projet.

Deux gardes neuves sont nées de cette tranche : `tests/architecture` lit maintenant les
`source` des scripts shell (un produit ne peut pas sourcer un autre), et
`tests/architecture/test_gardes.py` refuse qu'un produit CESSE d'appeler une garde — avec,
dans son message, la panne qu'on s'apprête à retrouver. 12 tests de frontière deviennent 22.

**Ce qui n'est PAS partagé est écrit dans `CLAUDE.md`, avec la raison de chaque ligne.** Le
lire avant de « finir le travail » : partager la configuration de construction du front
ferait résoudre vite et ses greffons depuis le `node_modules` du socle, et une image de base
commune devient un prérequis de chaque déploiement.

## La panne des campagnes est résolue

**Cause établie le 27/10, reproduite 6 fois sur 6** : elle était dans notre boucle
d'attente, pas dans la machine. L'entrypoint de `postgres:16` lance un serveur
**temporaire** pendant `initdb`, qui n'écoute que la socket Unix ; `pg_isready` y répond,
puis repasse en échec quand l'entrypoint l'arrête pour démarrer le vrai. La boucle sortait
sur ce premier succès, puis posait une **seconde sonde indépendante** qui, tombée dans la
fenêtre d'arrêt, annonçait « jamais prêt après 180 s » en quelques secondes.

Correctif : sonde en TCP (`-h 127.0.0.1`), que le serveur temporaire n'expose pas, et
décision **dans** la boucle sur trois succès consécutifs. Vérifié 6/6, prêt en 4-5 s.
Les campagnes repartent.

## Ce qui attend Gael, et qui bloque

- **40 tickets en revue**, dont `66391afe` et `844f15ad`. Toute la chaîne d'ingestion
  (`4d4fdcef` → `d680e811` → `c705e801`) est derrière `66391afe`.
- Le ticket `c705e801` renvoie à un **« epic de la fabrique »** (génération du script
  d'initialisation, calcul de la stack) **qui n'existe pas dans le backlog**. Sans lui,
  le ticket consomme un schéma que personne ne produit. Signalé le 27/10.

## Ce qui est éligible, et par quoi commencer

- `6a0daab6` — **l'échange de clés à l'appariement**. C'est la tête de file : ses **trois
  prérequis sont livrés** depuis le 28/10, et la section « Prérequis » de son corps est
  désormais à jour. Les deux côtés existent, chacun avec sa stack et sa base ; le socle
  porte déjà les clés et les appels signés, et l'environnement porte sa paire persistante.
  Ce qui reste est le protocole lui-même — demande en attente, code TOTP brûlé à l'usage,
  dépôt mutuel des clés publiques — plus le côté enrôlement de la route de pair.
- `31025fe6` — modèles « Devices entrants » / « Devices sortants ».
- `449e1694` — famille « Sources » : le schéma de ce qu'une source reçoit.
- `8474baf4` — **le référentiel n'affiche plus l'appariement**. Décidé par Gael le 29/10 :
  c'est une liste d'environnements à assigner, pas un second écran d'appariement. Attention,
  l'API garde `paired_base_url` — le sélecteur s'en sert pour écarter les déjà appariés.
- `8803f092` — **changer l'environnement d'un appariement conclu**, tant qu'il ne porte
  aucun device. Renverse en partie la règle de `bf2115cd` : les commentaires qui disent
  « révoquer puis réapparier » sont à corriger avec.
- `2edf1f3c` — **le module d'environnement affiche l'environnement qui lui est assigné**,
  lu chez l'enrôlement et mémorisé, avec repli daté sur la dernière valeur connue.
- `c51a732c` — **déplacer en bloc les devices d'un environnement**. Bloqué par le parc.
- Le **métier** de l'enrôlement : la coquille ne porte rien de lui. Référentiel des
  devices, enrôlement d'une installation, dispatch, parc, tags, groupes — autant de
  tickets de l'epic *Module d'enrôlement*.

**`6a0daab6` est devenu éligible le 28/10** : ses trois prérequis sont en revue. Son corps
porte toujours la section « Prérequis », mise à jour — la lire, elle dit ce qui existe et
sous quelle forme, ce qui évite de reconstruire ce qui est déjà là.

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
ces deux-là en parallèle → `6a0daab6` (échange de clés). **Les trois premiers sont en revue
depuis le 28/10**, et la chaîne est donc franchie.

**Ce chaînage n'est pas déclaré en propriété sur `6a0daab6`** : `bloque_par` n'accepte qu'une
`story`, et les trois prérequis sont des `enabler`. Le statut ne peut pas le porter non plus —
un `story` n'a que `nouveau / à faire / en cours / en review / done`, aucun rôle « bloqué ».
Faute de mécanisme, **`6a0daab6` porte ses prérequis en tête de son corps** (section
« Prérequis : trois produits à monter avant que ce ticket soit faisable », écrite le 27/10) :
son statut le montre toujours éligible, c'est cette section qui dit le contraire. La lire
avant de prendre le ticket.

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

- **Un journal de campagne de 77 octets n'est pas un succès.** Sept échecs du 24 au 27/10
  sur « PostgreSQL jetable jamais prêt », campagne jamais lancée. J'ai annoncé « 0 échec »
  trois fois sur un compteur qui ne pouvait pas être non nul avant la fin. **La cause est
  établie depuis le 27/10 et corrigée** (voir ci-dessus) : elle était dans notre boucle.
  On avait écarté machine, disque, mémoire, image, réseau et contention — tout sauf le
  code qu'on avait écrit. La leçon de lecture, elle, reste entière : vérifier la taille du
  journal ET les trois lignes de résumé avant d'annoncer un verdict.
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
cd socle/python        && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd socle/web           && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
cd portail/backend     && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd portail/frontend    && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
cd enrolement/backend  && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd enrolement/frontend && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
cd environnement/backend  && uv run ruff check src tests && uv run mypy src && uv run pytest -q
cd environnement/frontend && npx tsc --noEmit -p tsconfig.json && npx eslint src/ && npx vitest run
cd tests && uv run pytest -q                # frontière socle / produits — à lancer après
                                            # tout déplacement de code entre les racines
<produit>/dev-deploy.sh                     # livrer, PORTAL_TOKEN sur stdin, jamais en argv
<produit>/scripts/run-integration-tests.sh  # campagne, à lancer détachée
```

**Neuf racines, neuf environnements.** `socle/python`, les trois `<produit>/backend` et
`tests` ont chacun leur `pyproject.toml` et leur verrou ; `socle/web` et les trois
`<produit>/frontend` ont chacun leur `package.json`, leur verrou et leur `node_modules`.
`uv sync` ou `npm ci` dans l'une ne fait rien pour les autres, et un vert dans une seule ne
dit rien des huit suivantes. **Toucher à un socle oblige à repasser sur ses TROIS
consommateurs** — et la campagne du portail, qui dure vingt-cinq minutes, en fait partie.

Le reste — machine de test, annuaire, compte d'amorçage, pièges de déploiement — est dans
`tests_and_ressources.md`, à côté.
