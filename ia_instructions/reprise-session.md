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
| `portail/` | Portail de configuration — le **module de paramétrage** | livré, déployé sur test1, **port 8080**. **S'apparie au module d'enrôlement** depuis le 29/10 (ticket `ba44914b`) |
| `enrolement/` | Service d'enrôlement | coquille le 27/10 ; **sert le protocole d'appariement** depuis le 28/10 (ticket `6a0daab6`), **port 8081**, pour **deux espèces de demandeur** depuis le 29/10. Le parc des devices reste à faire |
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

## Le portillon du portail, et l'adresse de contact (29/10, ticket `1ce685e9`)

**À lire avant de toucher aux appels entre modules.** C'est le défaut qui a coûté le plus
de temps à diagnostiquer, et il n'était ni dans les clés ni dans le protocole.

- L'annuaire `dev.yoops.org` place un **portillon d'authentification devant tout service
  exposé**, `/api/health` compris. Un appel vers `https://svc-miles-miles-*.yoops.org/...`
  reçoit `302` vers `https://dev.yoops.org/auth/login`.
- La mesure qui tranche : la MÊME requête signée, par l'URL publique, rend 302 et le module
  **n'en garde aucune ligne de journal** ; droit sur le module (`http://100.74.9.236:8081`),
  elle rend un 401 que le module a lui-même calculé, avec sa ligne. La requête n'arrivait
  pas — les credentials étaient bons depuis le début.
- **L'adresse composée n'entre dans AUCUNE signature.** La chaîne canonique porte l'origine
  de l'ÉMETTEUR, la méthode, le chemin et l'empreinte du corps. Jamais l'hôte appelé.
- D'où le correctif : `enrolment_peer` porte `contact_url` **en plus** de `base_url`.
  L'identité (`base_url`) sert à UNE chose — comparer l'origine déclarée d'un appel
  entrant —, l'adresse de contact sert à composer. Un appel entrant qui déclare l'adresse
  de contact est **refusé**, et un test le prouve : elle est choisie chez nous, l'accepter
  comme identité authentifierait une origine que le pair n'a jamais revendiquée.
- L'adresse de contact est celle que l'administrateur **tape** à la demande d'appariement ;
  elle était jetée jusque-là. On la change par un ré-appariement, ou par
  `PUT /api/identity/peer` qui l'accepte sans toucher aux clés.
- **L'appariement vivant de test1 est repointé** sur `http://100.74.9.236:8081` et
  refonctionne (`state = apparie`), même clé `82876eb0…`. En `http` : le maillage est
  chiffré, et le seul secret qui y transite est le code d'appariement, à usage unique et
  d'une fenêtre de 30 s.
- **Ne pas « simplifier » les deux champs en un.** C'est ce qui fait marcher les appels.

## L'avis de révocation (29/10, ticket `4ce141d3`)

Premier et seul appel dans le sens **enrôlement → environnement**. Il renverse une phrase
du contrat, et la crainte qu'elle portait reste vraie.

- **Pourquoi il existe** : l'écran de l'environnement disait « son administrateur a PU
  révoquer, OU les clés ne se correspondent plus ». Il énumérait parce qu'on refusait de
  le lui dire — révoquer DÉTRUIT la clé publique du pair, donc répondre « tu es révoqué »
  à qui déclare cette origine l'apprendrait à n'importe quel inconnu. L'avis POUSSÉ lève
  la contradiction : signé de notre clé, qu'il détient déjà.
- **Il est AU MIEUX.** Stack éteinte, en panne ou qui refuse l'avis : révoquée quand même.
  Ne jamais faire dépendre la révocation d'une réponse réseau — ce serait donner à la
  stack révoquée le pouvoir de refuser sa propre révocation.
- **L'avis DÉSAMBIGUÏSE, il ne remplace pas.** L'écran ping toujours le pair ; l'avis
  nomme la cause du refus constaté. Un avis seul ne dit rien, et **un avis que les faits
  démentent est oublié** — c'est ce qui rend inoffensif un avis arrivé juste avant un
  ré-appariement, cas qu'aucune corrélation ne pourrait trancher puisque l'avis ne porte
  aucun identifiant d'appariement.
- **L'enrôlement porte à son tour une adresse de contact** (`environment_peer.contact_url`,
  migration 13), mais avec la règle INVERSE : saisie par son administrateur, et **jamais
  réécrite au ré-appariement**. Côté environnement elle vaut l'adresse qu'on vient de
  composer ; ici elle vaut ce qu'un humain a décidé. Les deux sont justes.
- **Pourquoi elle n'est pas déclarée par la stack** (arbitrage de Gael) : l'enrôlement
  émettrait sinon des appels signés vers une adresse choisie par un tiers que personne
  n'a authentifié au moment où il frappe. Celui qui compose reste maître de ce qu'il compose.
- `post_signed` est passé **au socle** : deuxième usage, c'est la règle du dépôt.
- **Éprouvé en vrai sur test1**, cycle complet : appariement par le maillage, adresse de
  contact saisie, révocation → `avis_de_revocation_remis` / `avis_de_revocation_recu`,
  état `revoque` daté. L'appariement vivant a été rétabli après.

## Le référentiel n'est plus un écran d'appariement (29/10, ticket `8474baf4`)

L'écran « Environnements déclarés » n'affiche plus **aucun** état d'appariement : ni
« Apparié / Non apparié », ni l'URL de la stack appariée, ni la demande en attente. Il
déclare, l'autre écran assigne. Deux écrans qui montrent le même état finissent par se
contredire.

- `paired_base_url` et `designated_base_url` **restent** dans l'API et dans le modèle du
  front : le sélecteur de l'écran d'appariement lit le premier pour ne pas proposer un
  environnement déjà apparié. Le commentaire du modèle le dit, parce qu'un champ que plus
  aucun écran n'affiche se « nettoie » au premier passage.
- Le **refus de supprimer** un environnement apparié reste, et c'est lui — pas une colonne
  — qui dit à l'humain pourquoi il ne peut pas.
- Le critère 12 du ticket `d5ffeb33` (« le référentiel montre non apparié après
  révocation ») **tombe** : la liste ne montre plus d'état du tout.

## Changer l'environnement d'un appariement conclu (29/10, ticket `8803f092`)

Arbitrage de Gael : le changement direct est ouvert, **tant que l'appariement ne porte
aucun device**. Il renverse la règle « révoquer puis réapparier » du ticket `bf2115cd`.

- **Un geste côté humain, deux faits côté journal.** `PUT /api/pairing/peers/environment`
  pose l'environnement d'un appariement conclu ; l'event est
  `pairing.environment_attached` s'il n'y avait rien, `pairing.environment_moved` sinon,
  avec les trois champs `previous_environment_*`. Ces champs sont **absents et non nuls**
  au rattachement : un `null` ferait chercher un déplacement qui n'a pas eu lieu.
- **La garde des devices vit en UN SEUL endroit nommé** : `_refuse_if_devices`, qui lit
  `db_count_peer_devices`. Cette fonction **rend zéro partout** — le référentiel des
  devices n'existe pas encore —, donc la garde **ne mord sur rien en vrai**. C'est dit, et
  c'est le point précis à rebrancher sur le parc. Un test lui injecte un compte non nul
  pour éprouver qu'elle mord.
- **Ne pas confondre avec le `null` de l'API.** `device_count` vaut `null` parce qu'on ne
  sait pas compter et que l'écran affiche « — » ; la garde a besoin d'un **compte**. L'une
  informe un humain, l'autre décide.
- **Trois refus distincts, et c'est exprès** : `appariement_porte_des_devices` renvoie vers
  le déplacement des devices, `appariement_change_ailleurs` est une **course** dont le
  remède est de relire la liste, `appariement_conclu` dit que le changement se fait sur
  l'appariement et non sur la demande d'une stack qui refrappe. Fondus, ils feraient croire
  le geste interdit alors qu'il est permis.
- `environment_id IS NOT DISTINCT FROM $4` dans l'écriture **généralise** l'ancien
  `IS NULL` : c'est ce qui ferme la course de deux onglets sur la MÊME ligne, qu'aucune
  contrainte d'unicité ne rattraperait.
- **Mesuré** : retirer la lecture préalable `_refuse_if_taken` laisse toute la suite verte
  — le refus d'un environnement déjà pris vient bien de la **contrainte**, pas de cette
  lecture. C'est le critère 3, prouvé plutôt qu'affirmé.
- **Éprouvé en vrai sur test1** : l'appariement vivant déplacé `recette` → `dev`, le
  référentiel a libéré `recette`, reposer `dev` n'a rien écrit, puis retour sur `recette`.
  Le journal porte deux `pairing.environment_moved` et rien pour le no-op.

## L'environnement assigné, lu chez l'enrôlement (29/10, ticket `2edf1f3c`)

Le module d'environnement affiche enfin **l'environnement du référentiel** auquel
l'enrôlement l'a rattaché — le seul nom qui fasse autorité, posé par un humain là-bas,
alors que le nom déclaré est ce que la stack dit d'elle-même.

- **Une route de pair de plus** : `POST /api/peer/environment`, servie par l'ENRÔLEMENT,
  appelée par l'ENVIRONNEMENT. Vérifiée contre la clé du pair apparié, donc chacun ne lit
  que son propre rattachement. Contrat en **révision 9**, septième amendement.
- **Pourquoi pas un champ de plus dans le `pong`** : il est servi par les DEUX modules avec
  la même forme de réponse, et c'est ce qui permet à `PongOut` d'être défini une seule fois
  au socle. Un champ qui n'existe que d'un côté ferait porter au `pong` un nul permanent
  chez l'autre. Une route de plus ne change rien à l'existant.
- **Le slug et le libellé, jamais l'identifiant** : c'est la clé du référentiel de
  l'enrôlement, et la faire voyager inviterait à écrire une relation entre deux bases que
  personne ne réconcilie. Un test vérifie qu'elle ne sort pas.
- **`null` et non 404** quand rien n'est rattaché (appariement hérité) : un 404 se lirait
  « cette route n'existe pas chez lui », ce que rend son portillon d'authentification.
- **Le repli est assumé et se dit.** La valeur est mémorisée avec sa date (migration 13 de
  l'environnement) et réaffichée datée quand le pair est injoignable. Quatre cas que
  l'écran distingue, et `fresh` est PORTÉ par la réponse au lieu d'être déduit de la
  présence d'une valeur : « injoignable et jamais rien su » et « le pair dit qu'il n'y a
  rien » rendent tous deux `null`, et les confondre annoncerait « aucun environnement » à
  un administrateur dont le réseau est coupé.
- **Un refus n'efface rien.** Révocation, clés qui ne se correspondent plus, portillon qui
  parle avant lui : rien de tout cela ne dit qu'on n'est rattaché à rien. Seule une
  réponse FRAÎCHE qui dit `null` efface la valeur mémorisée.
- **La réponse est relue par le modèle du contrat** avant d'être écrite : un 200 ne
  garantit pas la forme, et ranger ce qu'un inconnu renvoie l'afficherait comme l'autorité.
- **La mémoire survit à un ré-appariement du MÊME pair** et s'efface si l'identité du pair
  change — l'inverse de `revoked_at`, effacée dans tous les cas : une date de révocation
  sur un appariement vivant se contredit, un rattachement périmé est seulement vieux, et il
  le dit.
- **Éprouvé en vrai sur test1** : lecture fraîche de `recette` à travers le maillage, puis
  adresse de contact repointée sur un port mort → `fresh: false` avec la date de la
  lecture précédente et `environnement_assigne_injoignable` au journal, puis retour sur le
  maillage → date neuve. L'appariement est resté `apparie` tout du long.

## Le module de paramétrage s'apparie, et le côté demandeur passe au socle (29/10, ticket `ba44914b`)

**Le plus gros déplacement de code depuis le découpage en trois produits.** Le ticket
demandait d'apparier le module de paramétrage au module d'enrôlement et interdisait
nommément d'en dupliquer le mécanisme : « si celui de l'environnement ne se réemploie pas
tel quel, c'est qu'il est à généraliser, pas à dupliquer ». Il s'est donc généralisé.

**Ce qui est parti au socle** — tout le côté DEMANDEUR :

- `socle/python/src/miles_socle/pairing/` : le pair unique, ses refus, les gestes
  (frapper, coller le code, annuler), le constat de l'état, les deux sens de l'échange,
  la réception de l'avis de révocation, les routes d'administration sous `/api/identity`
  et les routes de pair. Le service s'appelle `PairingRequesterService`.
- `socle/web/src/peering/` et `socle/web/src/api/peering.ts` : l'écran et son client
  d'API. Espace de noms i18n **`peering`**, volontairement distinct du `pairing` de
  l'enrôlement — celui-là nomme ce qu'on SERT, celui-ci ce qu'on DEMANDE, et les fondre
  ferait que les clés de l'un masqueraient celles de l'autre à la fusion.
- `miles_socle.testing.enrolment_double` : la doublure du module d'enrôlement, employée
  par les deux demandeurs. Elle double le PROTOCOLE, défini au socle.

**Ce que chaque produit déclare encore, et c'est tout** : `module_name`, `species`,
`key_label`, portés par sa sous-classe du service (jamais par ses sites de câblage, qui
divergeraient), et **ses tables** — le socle ne porte aucune migration.

**L'espèce du demandeur** (`environnement` | `parametrage`) est au contrat
(`signing/protocol.py`), **facultative** dans la demande d'appariement : absente, elle vaut
`environnement`, qui était la seule espèce possible avant ce jour. Rien n'est rompu.

- Elle est **déclarée**, donc elle n'autorise rien : c'est le geste humain — révéler le
  code — qui autorise, et l'écran affiche l'espèce AVEC sa conséquence (« reçoit des
  devices » / « se verra confier les connexions git »), parce que le libellé seul ne dit
  pas à un humain ce qu'il donne.
- **Un seul module de paramétrage apparié**, par index unique PARTIEL sur `species` :
  l'unicité ne vaut que pour cette espèce, les environnements restant N par construction.
  Un test mesure les deux, parce qu'un index posé sur toute la colonne serait vert dans
  une suite qui n'apparie qu'un environnement à la fois.
- La **désignation d'un environnement** est exigée de l'espèce `environnement` et REFUSÉE
  à l'autre (`espece_sans_environnement`). Le code du module de paramétrage est donc
  révélable sans désignation : c'est la seule différence de parcours.
- Une origine appariée **ne change pas d'espèce** en se réappariant. Le refus est posé à
  DEUX endroits : devant l'humain, au geste qui révèle le code (sinon il désignerait un
  environnement pour rien), et dans la clause `ON CONFLICT … WHERE species = excluded.species`
  de l'écriture, qui est la seule garde atomique. Le second a son propre test, sinon le
  retirer ne ferait rougir personne.

**Ce que la migration 14 de l'environnement défait, un jour après l'avoir posé.** La
mémoire de l'environnement assigné vivait en trois colonnes de `enrolment_peer`, et
l'invariant « elle meurt quand l'identité du pair change » était tenu par trois clauses
`CASE WHEN` dans l'upsert du pair. Cet upsert est parti au socle : une requête partagée ne
peut pas porter le nom de colonnes qui n'existent que dans un produit. La mémoire a donc
sa **table**, `assigned_environment`, rangée sous l'ORIGINE du pair qui l'a dite — la
lecture joint sur le pair courant, et l'invariant est devenu une jointure au lieu d'être
une clause à ne pas oublier. Conséquence meilleure que l'ancienne : revenir chez un
enrôlement qu'on avait quitté retrouve ce que CELUI-LÀ avait dit, non frais et daté.

**Ce qui reste à faire, et le ticket le dit** : son critère 4 demande que la révocation
« emporte les connexions git confiées ». **Rien n'est confié** — la transmission est le
ticket voisin `edcf78bc`, qui dépend de celui-ci et décidera de sa forme. Inventer ici une
couture vide aurait figé un design qui n'est pas le nôtre à décider.

**Le nom de la table `environment_peer` n'a PAS changé**, alors qu'elle porte désormais les
deux espèces. Renommer coûterait la rupture du genre d'objet `environment_peer` des events
déjà écrits — l'historique de chaque appariement se couperait en deux — pour le seul gain
d'un nom plus juste. C'est dit en commentaire à la table et au modèle, pour que personne ne
le lise comme un oubli.

## Les connexions git confiées au module d'enrôlement (30/10, ticket `edcf78bc`)

**Ce qui donne enfin un contenu à l'appariement du module de paramétrage.** « On ne va pas
s'amuser à rentrer plusieurs fois les infos de connexion git » (Gael, 27/10) : elles sont
saisies une fois dans le portail, et elles arrivent chez l'enrôlement sans que personne ne
retape rien.

**La décision de sécurité qui porte le ticket : le secret s'arrête au module
d'enrôlement.** Un module d'environnement n'en reçoit jamais le credential — il lira git
par un relais, reporté par Gael. Deux propriétés en découlent, et ce sont elles qui
justifient la chaîne plutôt qu'une distribution : un environnement compromis ne livre pas
l'accès au dépôt, et un environnement révoqué perd son accès à git sans qu'on révoque quoi
que ce soit chez la forge.

**Le paramétrage POUSSE, et c'est lui qui a l'information.** Le ticket laissait le sens
libre. Celui qui sait quand une valeur change est celui qui détient le clair : poussant, il
transmet au moment du changement. Si l'enrôlement interrogeait, il faudrait qu'il sache
quand demander — donc qu'il tienne pour vrai, entre deux interrogations, un credential déjà
remplacé — et toute lecture de git dépendrait de la disponibilité du portail.

**C'est l'ÉTAT COMPLET qui part, jamais un écart.** Un écart exige un ordre, un accusé et
une file à rejouer ; l'état converge de lui-même, et la **suppression d'une connexion n'a
pas de message à elle** — absente de l'état, elle est détruite là-bas. Une révision
strictement croissante, allouée au moment où l'état est lu, fait refuser une photo ancienne
arrivée en retard.

**Trois verrous pour l'interdit central, et aucun ne remplace les autres :**

1. l'appel est signé par la clé du pair apparié ;
2. l'**espèce** du pair est vérifiée avant toute écriture, et le refus la nomme
   (`espece_sans_connexions_git`) ;
3. la **base** refuse, par une clé étrangère composée vers `(base_url, species)`, qu'une
   connexion git confiée appartienne à autre chose qu'un module de paramétrage. Un test
   écrit en SQL ce qu'aucune route n'offre — sans lui, retirer la clé étrangère ne ferait
   rougir personne.

Plus un **test d'architecture** (`tests/architecture/test_credentials.py`) : aucun nom
porteur de credential n'est atteint par `environnement/`, backend comme front, avec un
second test qui vérifie que ces noms existent toujours au contrat — sinon un renommage
désarmerait la garde en silence.

**Où le credential est rangé, et pourquoi pas dans `secrets`.** Le critère demandait de
reprendre ce qu'on a fait pour les secrets du workspace : c'est le **chiffrement** qui est
repris — même AES-GCM, même `MILES_SECRETS_KEY`, données associées liant le chiffré à sa
ligne. Pas la table, et pour trois raisons : un credential confié n'est pas un secret de
l'instance, personne ici n'a le droit de le remplacer à la main — l'écran des secrets le
permettrait, et ce serait la ressaisie que le ticket supprime —, et sa durée de vie est
celle de l'appariement, alors que `secrets` refuse justement la suppression d'un secret
utilisé. **La révocation le détruit par cascade**, jamais ne le marque inactif : une ligne
inactive porte encore le secret.

**Deux rappels après commit, et ils sont tardifs à dessein.** Un PAT remplacé dans l'écran
des secrets — servi par le socle — et un appariement tout juste conclu doivent déclencher
une transmission. Le socle a donc un `on_value_replaced` optionnel, et le `PairingService`
du portail un `on_paired` ; les deux sont câblés par des fermetures qui relisent
`app.state` **au moment de l'appel**, parce que le service qui confie a besoin du service
d'appariement pour signer : capturer l'un des deux à la construction serait un cycle.

**La divergence est visible, jamais silencieuse.** Le portail garde l'empreinte de ce qu'il
a transmis et à QUI — rangée sous l'origine du pair, donc elle cesse de s'appliquer dès que
l'identité du pair change (même leçon que l'environnement assigné, la veille) — la compare
à ce qu'il détient, et son écran dit « à retransmettre ». Un geste explicite rejoue la
transmission, et celui-là **rend le refus** au lieu de l'avaler. **Il n'y a pas de réessai
automatique** : le retenter en boucle demanderait l'outbox du ticket `7ae31cc0`, qui n'est
pas fait. C'est une limite assumée, pas un oubli.

**Ce que le ticket ne pouvait pas livrer, et pourquoi.** Le critère 6 — « credential
invalide ou révoqué chez la forge : l'erreur dit que c'est le credential qui est en cause,
et où il a été saisi » — suppose qu'un module LISE git avec un credential confié. Aucun ne
le fait : le relais est hors périmètre, reporté par Gael dans le ticket lui-même. Ce qui est
livré de ce critère est ce qui existe aujourd'hui : l'écran de l'enrôlement éprouve un
credential confié — s'ouvre-t-il encore avec la clé de cette instance ? — et nomme
l'échec comme un problème de CREDENTIAL, en renvoyant vers le module de paramétrage. Les
deux autres refus de diagnostic (aucun module de paramétrage apparié, connexion supprimée à
la source) sont nommés et distincts, parce qu'ils n'appellent pas le même geste.

## Les référentiels donnés du portail : les pays (30/10, story `ccd8703c`)

**Sujet ouvert par Gael le 30/10, et il a bougé deux fois avant de se poser.** Demandé
d'abord dans le module d'enrôlement, puis « dans configuration », puis « dans la partie
global » — c'est-à-dire la **section Global du menu du portail**, celle de « ce que
partagent tous les workspaces », où vivent déjà les cultures. C'est la dernière
formulation qui vaut.

**Le cadrage avait déjà tranché le dispositif**, et c'est ce qui a évité d'en inventer un :
« Cultures : un référentiel donné, qu'on active » (Gael, 15/10/2026). La liste est en base,
complète, chargée par une migration engendrée ; l'administrateur n'y fait qu'**activer**,
avec un filtre. Les pays reprennent cela à l'identique, pour la même raison : 249 entrées
ne se choisissent pas dans une liste déroulante.

**Cinq décisions prises avec lui, et elles sont dans la feature `f6e54dee`** : le portail
(pas l'enrôlement, pas le socle) ; en base pour l'instance (pas dans git) ; les deux listes
seules, rattachées à rien ; **un libellé par culture active, donné par CLDR et dérivé à la
lecture** ; et le fuseau portera son pays.

**Ce qui a demandé une question de plus** : « un libellé par culture active » ne dit pas
d'où vient le libellé. Les charger par migration aurait obligé à choisir POUR QUELLES
cultures — 249 pays pour les ~800 du référentiel font deux cent mille lignes de SQL, et
s'en tenir aux langues laisse sans libellé toute culture non prévue. Les faire saisir est
exclu : personne ne tape 249 noms de pays dans trois langues. D'où la dérivation à la
lecture, et son prix assumé : **`babel` est une dépendance d'EXÉCUTION du portail**, là où
elle n'était qu'un outil de génération. Le gain se constate : activer une culture de plus
donne aussitôt ses libellés, sans migration ni saisie.

**L'alpha-2 voyage sur la ligne à côté du slug alpha-3**, et ce n'est pas un détail
d'implémentation qui fuit : **CLDR indexe les territoires en alpha-2**. Sans lui, aucun
libellé n'est dérivable. Le slug reste l'alpha-3, qui est ce que Gael a demandé et ce
qu'une procédure d'exploitation écrit.

**Le mot « référentiel » n'apparaît ni dans le module, ni dans les routes, ni à l'écran.**
Il désigne déjà trois autres choses dans ce produit — les référentiels d'objets ingérés,
ceux de mapping dans git, les storages. L'écran s'appelle « Pays », la route
`/api/countries`, le module `miles/reference/`.

**La règle de repli des libellés a trois branches**, et elle est éprouvée sans base parce
que c'est une fonction pure : la culture du visiteur **si elle est active**, puis `en-US`,
puis le slug. Jamais un vide, jamais le libellé d'une autre culture — « Deutschland »
affiché à un visiteur français laisserait croire à une donnée mal saisie, alors que rien
n'est saisi. Mesuré : les 249 pays ont tous un libellé `en-US`, donc la troisième branche
est inatteignable aujourd'hui ; elle est gardée pour une révision de l'ISO plus rapide que
CLDR, et pour les fuseaux qui réemploieront la même règle.

**Une garde que la campagne ne mesurait pas**, trouvée en écrivant l'injection : la
validation de la culture est doublée par la capture d'erreur de `_locale`, donc la retirer
laissait tout vert. Elle a maintenant son test à elle — ce qu'elle seule apporte est
d'empêcher une chaîne arbitraire de servir de clé au cache de locales.

## Les fuseaux horaires, et ce que la mesure a corrigé (30/10, story `d4fb364a`)

**Jumeau du référentiel des pays**, livré le même jour. 312 zones, activation, filtre,
libellés dérivés de CLDR — rien de neuf dans le dispositif. Ce qui a demandé du travail,
c'est la DONNÉE : **trois mesures ont renversé trois décisions que j'aurais prises de
mémoire**, et c'est le seul enseignement durable de cette story.

| Ce que j'aurais fait | Ce que la mesure a dit |
| --- | --- |
| Écarter les alias en filtrant les clés de `zone_aliases` (CLDR) | Il va du nom **canonique vers l'ancien** (`Europe/Kyiv` → `Europe/Kiev`) : filtrer sur ses clés retire les BONS noms |
| Un pays par fuseau | `Asia/Dubai` en sert cinq, et **93 pays** n'apparaissent jamais en première position — ils seraient tous sans aucun fuseau |
| Ajouter `UTC`, pour le cas « sans pays » | CLDR n'en a aucun nom et rend « heure : région indéterminée (UTC) ». Retiré : la table IANA l'exclut parce que ce référentiel qualifie des **lieux** |

**La source est la table IANA `zone1970.tab`**, pas CLDR : elle seule donne les zones
canoniques (312, contre 486 identifiants système mélangeant les noms obsolètes et
`localtime`) et tous les pays de chacune. CLDR ne sert plus qu'aux libellés.

**Conséquence de la troisième mesure** : aucune entrée n'est sans pays, donc le critère qui
prévoyait ce cas est tombé. Il venait d'une mesure CLDR (`Antarctica/Troll` rattaché au
monde) que la source IANA rend fausse — elle lui donne `AQ`. **Le ticket a été corrigé
avant l'écriture du code**, deux fois, et c'est ce qu'il faut faire : un ticket qui cite un
exemple faux induit le suivant en erreur.

**Le libellé ne désigne pas le fuseau**, et l'écran en tient compte : CLDR rend un nom de
MÉTAZONE — « heure d'Europe centrale » vaut pour Paris, Berlin et Madrid. L'identifiant
IANA est donc affiché à côté, toujours. Le test qui le prouve monte deux fuseaux au
**même** libellé : sans l'identifiant, les deux lignes seraient indiscernables.

**Le décalage horaire n'est PAS stocké**, et l'écran le dit : il dépend de la date et des
règles d'heure d'été, qui changent plusieurs fois par an. Une valeur en base serait fausse
six mois sur douze, et fausse en silence.

**L'activation est extraite au second usage** (`reference/activation.py`), comme la règle
du dépôt le demande. C'est la partie à invariants — verrou avant écriture, tout ou rien,
« déjà dans l'état voulu n'est pas un changement ». La mesure de la refactorisation : les
tests des pays passent **sans modification**. Et un test mesure que les deux référentiels
ne partagent pas leur état — sans lui, un descripteur mal câblé ferait activer des pays
depuis l'écran des fuseaux, les deux campagnes restant vertes chacune de son côté.

**Un jeu d'essai écrit de mémoire a été corrigé par la campagne** : `Europe/Paris` sert la
France **et Monaco** (`FR,MC` dans la table). Le code avait raison, l'assertion non.

## L'assainissement des modules d'appariement (29/10, ticket `f85d248e`)

`PairingService` et `IdentityService` restent **une classe chacune**, découpées en
plusieurs fichiers par héritage — aucune indirection ajoutée à l'exécution. Le plus gros
fichier des deux modules est passé de 667 à 261 lignes.

- Les annotations des collaborateurs sont **dupliquées** sur la classe de base : mesuré,
  `dataclasses` ne collecte que les annotations de la classe qu'il décore, donc les vrais
  champs restent sur la classe concrète. mypy refuse qu'elles divergent.
- Trois noms privés traversaient un module : un `_` qui s'importe ailleurs est un **faux
  privé**, ils sont nommés pour ce qu'ils font.
- Les **réexports explicites** (`as`) de `identity/service.py` ne sont pas des imports
  oubliés : le produit et sa suite les importent de là. `ruff --fix` les retire si on
  touche à la forme.
- Les listes de colonnes SQL restent écrites **littéralement** dans chaque requête, et les
  deux fichiers de store les répètent. Les factoriser serait la faute (ruff S608).
- **Restent 6 fichiers du portail et du socle** entre 307 et 380 lignes. Hors périmètre,
  autre produit, autre campagne — le ticket les liste.

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

- `31025fe6`, `449e1694` et la suite ci-dessous. `6a0daab6` est **livré** depuis le
  28/10 : le protocole complet tourne des deux côtés.
- `31025fe6` — modèles « Devices entrants » / « Devices sortants ».
- `449e1694` — famille « Sources » : le schéma de ce qu'une source reçoit.
- `c51a732c` — **déplacer en bloc les devices d'un environnement**. Bloqué par le parc.
- Le **métier** de l'enrôlement : la coquille ne porte rien de lui. Référentiel des
  devices, enrôlement d'une installation, dispatch, parc, tags, groupes — autant de
  tickets de l'epic *Module d'enrôlement*.

**En revue au 29/10 au soir** : `d5ffeb33` (révocation), `f85d248e` (assainissement),
`1ce685e9` (adresse de contact), `4ce141d3` (avis de révocation), `8474baf4` (le
référentiel n'affiche plus l'appariement), `8803f092` (changer l'environnement d'un
appariement conclu), `2edf1f3c` (l'environnement assigné) et `ba44914b` (le module de
paramétrage s'apparie), plus les tickets des jours précédents. Des quatre tickets neufs de
Gael du 29/10, il ne reste que `c51a732c`, bloqué par le parc.

**`edcf78bc` est livré le 30/10** — les connexions git sont confiées. Ce qu'il laisse
ouvert est nommé dans sa section : le **relais de lecture de git**, reporté par Gael, et le
**credential du registre d'images**, point ouvert de la feature. Aucun des deux n'a de
ticket éligible à ce jour.

**Ce qui reste des quatre tickets neufs de Gael du 29/10** : `c51a732c` seul, bloqué par le
parc, lui-même bloqué par `a4f05302`. Le **métier de l'enrôlement** est donc la suite
naturelle — référentiel des devices d'abord, puisque trois tickets l'attendent.

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
