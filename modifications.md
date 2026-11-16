# Modifications apportées à l'application « Suivi des congés »

Ce document explique, pour le service métier, ce qui a été modifié dans
l'application pour la mettre en conformité avec le guide technique de la Ville
(`GUIDE_NOUVELLE_APP_VILLE.md`), et pourquoi. Il est complété à chaque étape.

L'application reste identique pour les utilisateurs : mêmes écrans, mêmes
règles de calcul des congés.

## Plan global

1. Sécuriser l'identité des utilisateurs (fait)
2. Centraliser la configuration dans un fichier `.env` (fait)
3. Passer à la base PostgreSQL de la Ville, avec migrations versionnées (fait)
4. Connexion par l'Active Directory et envoi des mails via l'API centrale (fait, à activer avec la clé APM)
5. API versionnée (`/api/v1/`), clés API, page d'état et documentation Swagger (fait)
6. Conteneurs Docker, séparation frontend / backend pour la DMZ (fait, à tester sur un serveur Docker)

## Étape 1 — Sécurisation de l'identité (fait)

**Ce qui a changé**
- Après connexion, le serveur remet à l'utilisateur un cookie de session
  **signé**, valable 10 heures, inaccessible au JavaScript du navigateur.
- Le serveur ne croit plus l'identifiant que le navigateur lui annonçait.

**Pourquoi**
Avant, l'application identifiait l'utilisateur d'après un simple numéro envoyé
par le navigateur. Toute personne connaissant le numéro d'un compte (par
exemple celui de l'administrateur) pouvait se faire passer pour lui, sans mot
de passe. C'était particulièrement risqué pour une application partagée sur le
réseau, et inacceptable avant une exposition en DMZ.

**Impact pour les utilisateurs**
Aucun, hormis une reconnexion nécessaire après la mise à jour. La déconnexion
invalide désormais réellement la session.

**Vérifications**
Les tests existants passent, et un test manuel confirme qu'un faux identifiant
est refusé (erreur 401).

## Étape 2 — Configuration centralisée dans un fichier `.env` (fait)

**Ce qui a changé**
- Un module `config.py` regroupe tous les réglages : port, adresse d'écoute,
  emplacements de la base, des sauvegardes et des pièces jointes, durée de
  session, etc. Ils se renseignent dans un fichier `.env` placé à côté de
  l'application, jamais dans le code.
- Un fichier `.env.example` documente chaque réglage. Il contient déjà les
  emplacements prévus pour PostgreSQL, l'API centrale (APM) et le Hub DSI, qui
  serviront aux étapes suivantes.
- Le fichier `.env` est exclu du dépôt Git.
- **Le mot de passe `admin` / `admin` n'existe plus.** À la création d'une
  nouvelle base, le compte administrateur reçoit le mot de passe défini dans
  `.env`, ou un mot de passe aléatoire affiché une seule fois au démarrage.

**Pourquoi**
Le guide impose que ports, secrets et accès ne soient jamais écrits en dur et
qu'on puisse passer du développement à la production en changeant uniquement
`.env`. Un mot de passe par défaut connu de tous était en outre une faille
évidente avant toute exposition en DMZ.

**Impact pour les utilisateurs**
Aucun. Les installations existantes fonctionnent sans `.env` avec les mêmes
valeurs qu'avant, et leurs comptes ne sont pas modifiés. Les réglages d'envoi
de mail (`mail.json`) seront remplacés à l'étape 4 par l'API centrale.

## Étape 3 — Base PostgreSQL de la Ville, schéma dédié `conges` (fait)

**Ce qui a changé**
- Les données ne sont plus dans un fichier local (`suivi-conges.db`) mais dans la base
  PostgreSQL partagée de la Ville (`ivry_admin`), dans un **schéma à part, `conges`**.
  Aucune table des autres applications n'est lue ni modifiée.
- La structure de la base est décrite dans des **fichiers de migration numérotés**
  (dossier `migrations/`). Au démarrage, l'application applique seulement ceux qui
  manquent, et refuse de démarrer si un fichier déjà appliqué a été modifié. Les
  évolutions futures passeront par de nouveaux fichiers, plus par des `ALTER TABLE` épars.
- Les accès à la base (hôte, utilisateur, mot de passe) viennent du `.env`, jamais du code.
  Le fuseau horaire de la base est Europe/Paris.
- Les **données existantes ont été transférées** (56 comptes, 34 fiches, 340 cases de
  calendrier, 15 demandes, etc.) par le script `migrate_sqlite_to_pg.py`. L'ancien fichier
  SQLite n'a pas été modifié ni supprimé : il reste une copie de référence.
- Les dates restent stockées en texte, comme avant, pour ne pas toucher aux calculs. Leur
  conversion en vrais horodatages est prévue dans une étape ultérieure.
- La sauvegarde automatique du fichier SQLite a été retirée : la sauvegarde de la base
  PostgreSQL relève désormais de la DSI.

**Pourquoi**
Le guide impose le PostgreSQL de la Ville, un schéma par application et des migrations
versionnées. Cela supprime aussi la dépendance à un fichier posé sur un poste ou un serveur
(risque de perte, pas de gestion des accès concurrents) et permet à la DSI de superviser
et de sauvegarder la base comme les autres applications.

**Comment on a vérifié que rien n'a changé pour les utilisateurs**
- 114 écrans/consultations (tableaux de bord, planning, fiches, demandes, utilisateurs…),
  appelés pour chaque profil (administrateur, direction, service, secteur…) et chaque année,
  donnent **exactement les mêmes résultats** avec l'ancienne base et la nouvelle.
- Les opérations d'écriture (création/modification/suppression de comptes et de fiches,
  saisie de congés, demande puis validation et annulation) ont été rejouées sur une copie
  des données dans un schéma temporaire, ensuite supprimé.
- Les tests automatiques passent ; ils utilisent désormais un schéma temporaire qui est
  supprimé à la fin, sans toucher aux données réelles.

**À savoir**
- Le fichier `requirements.txt` liste les bibliothèques Python à installer
  (`pip install -r requirements.txt`).
- Les deux scripts ponctuels `migrate_agents.py` et `migrate_owner_restore.py` datent de
  l'ancienne base SQLite ; ils n'ont pas été adaptés et ne doivent plus être utilisés.

## Étape 4 — Active Directory et mails par l'API centrale de la Ville (fait)

**Ce qui a changé**
- **Connexion par l'Active Directory.** L'application peut vérifier le mot de passe des
  agents auprès de l'AD de la Ville, via l'API centrale (APM), au lieu de gérer ses propres
  mots de passe. Chaque compte garde son rôle et son rattachement hiérarchique dans
  l'application ; seul le contrôle du mot de passe change.
- **Nouveau champ « Identifiant AD »** (écran Utilisateurs). S'il est vide, l'identifiant de
  l'application est utilisé tel quel auprès de l'AD ; sinon on saisit l'identifiant Ville de
  l'agent quand il diffère.
- **Compte de secours.** Les comptes administrateurs gardent aussi leur mot de passe local :
  si l'AD ou l'APM est indisponible, un administrateur peut toujours se connecter. Pour les
  autres comptes, un message clair « service d'authentification indisponible » est affiché.
- **Mots de passe.** En mode AD, le changement de mot de passe dans l'application est
  refusé pour les agents (leur mot de passe est celui de leur compte Ville).
- **Mails par l'APM.** Les notifications aux valideurs et les relances partent par le service
  d'envoi de la Ville : le message est habillé du gabarit institutionnel, et le pied de page
  (3 lignes + couleur) est paramétrable dans `.env`. L'ancien réglage SMTP (`mail.json`) n'est
  plus utilisé. Un échec d'envoi n'empêche jamais l'enregistrement d'une demande.
- Un module unique (`apm.py`) concentre tous les appels à l'APM (clé, adresse, certificats).

**Pourquoi**
Le guide demande de ne pas réimplémenter ces services : l'authentification des agents passe
par l'AD, les mails par l'APM. Les agents n'ont ainsi plus de mot de passe supplémentaire à
retenir ni à faire réinitialiser, et la DSI garde la maîtrise (journal des appels, droits de
la clé, restriction par adresse IP). C'est aussi un prérequis pour une exposition en DMZ.

**Comment l'activer** (rien ne change tant que ce n'est pas fait)
1. Obtenir auprès de l'administrateur APM une clé propre à cette application, avec les
   permissions `ad_auth` et `mail_send`, et la renseigner dans `.env` (`APM_API_KEY`).
2. Renseigner l'« Identifiant AD » des comptes dont l'identifiant diffère de celui de la Ville.
3. Passer `CONGES_AUTH_MODE=ad` (connexion AD) et/ou l'envoi des e-mails dans Paramétrage > E-mails.

**Vérifications**
11 tests automatiques passent, avec un APM simulé : connexion locale, connexion AD (identifiant
AD utilisé, mot de passe local refusé), AD indisponible, secours administrateur, changement de
mot de passe refusé, mail envoyé avec pied de page et contenu protégé, échec d'envoi sans erreur.
**Non vérifié en réel** : aucun appel n'a été fait à l'APM avec une vraie clé (je n'en ai pas).
Seule l'accessibilité de `https://api.ivry.local` a été constatée.

**Limites connues**
- L'écran de création de compte et la création de fiche demandent encore un mot de passe
  (utilisé seulement en mode local ou pour les administrateurs). À simplifier une fois l'AD en service.
- Pas encore de limitation du nombre d'essais de connexion (prévu avec le durcissement DMZ).

## Étape 5 — API pour les autres applications, clés API, état de santé (fait)

**Ce qui a changé**
- **Une API en lecture seule, `/api/v1/`**, que d'autres applications de la Ville peuvent
  appeler : liste et identité des fiches, soldes d'une fiche (CA, RTT, JS, JB, CET…),
  absences saisies par demi-journée sur une période, demandes de congés et leur état.
  Les listes sont paginées. Aucune écriture n'est possible par cette API.
- **Clés API** : l'administrateur crée une clé par application (nouvel écran **Clés API**).
  Chaque clé a des **périmètres** (ex. « lire les fiches » mais pas « lire les soldes »),
  éventuellement une **liste d'adresses IP autorisées** et une **date d'expiration**. Elle peut être
  désactivée ou supprimée à tout moment. La clé n'est affichée qu'**une seule fois** à sa
  création et n'est pas conservée en clair. Chaque appel est journalisé (qui, quand,
  quelle route, quel résultat), sans contenu.
- **Documentation** : une page interactive (`/api-docs`) décrit toutes les routes ; elle est
  maintenue à jour par un test automatique qui échoue si une route n'y figure pas.
- **État de santé** : `/api/status` indique si l'application et sa base répondent
  (sans clé, sans donnée sensible), pour la supervision de la DSI.
- **Protections** : limitation du nombre d'appels par clé (120/minute), limitation des
  essais de connexion répétés (8 échecs sur 15 minutes par adresse), CORS fermé par défaut
  (seules les origines listées sont acceptées), prise en compte d'un reverse-proxy de confiance
  pour connaître la vraie adresse du client.

**Pourquoi**
Le guide demande des routes versionnées, une pagination, des erreurs normalisées, une
documentation Swagger, un point de santé et une protection contre les abus. L'API permet
à d'autres services (portail RH, annuaire, tableaux de bord) de réutiliser les données de congés
sans accéder à la base ni à l'écran, sous le contrôle de la DRH, qui décide qui lit quoi.
La limitation des essais de connexion était indispensable avant toute exposition en DMZ.

**Impact pour les utilisateurs**
Aucun sur l'existant : les écrans, routes et résultats internes sont inchangés (114
consultations comparées avant/après : aucune différence). Seul ajout visible : l'entrée
« Clés API » du menu, réservée aux administrateurs.

**Vérifications**
22 tests automatiques passent, dont : clé absente/invalide/révoquée/expirée refusées, périmètre
insuffisant, restriction par IP, clé jamais stockée en clair, pagination, correspondance des dates,
journal des appels, limitation de débit, blocage après échecs de connexion, CORS, documentation.
Serveur redémarré : `/api/status`, `/api-docs` et le refus sans clé répondent comme attendu.
L'écran « Clés API » a été essayé dans un navigateur sur une instance de test jetable (création d'une clé, affichage
unique, liste). **Non vérifié** : aucune application tierce réelle n'a appelé l'API.

**Limites connues**
- Les compteurs de limitation sont en mémoire : avec plusieurs processus serveur, la limite
  réelle est multipliée par leur nombre (à traiter avec l'étape Docker).
- Les routes internes de l'application (utilisées par l'écran) ne sont pas versionnées ;
  seules les nouvelles routes destinées aux autres applications le sont.
- Pas de rotation automatique des clés : on crée une nouvelle clé, on bascule l'application,
  puis on supprime l'ancienne.

## Complément — « Se connecter en tant que » pour les administrateurs (fait)

**Ce qui a changé**
- Un administrateur dispose d'un bouton **« Se connecter en tant que… »** dans la barre du haut. Il saisit
  quelques lettres (nom, prénom ou identifiant) : une **recherche prédictive** interroge l'annuaire Active
  Directory de la Ville (via l'APM) et propose les agents correspondants, complétés par les comptes de
  l'application (qui restent utilisables si l'AD est indisponible).
- En cliquant sur un agent, l'administrateur **agit avec exactement les droits de cet agent, sans connaître
  son mot de passe**. Un **bandeau rouge** rappelle en permanence « Vous agissez en tant que… » avec un bouton
  **« Revenir à mon compte »** ; la déconnexion y met aussi fin.
- Même principe que l'application delib.

**Garde-fous**
- Réservé aux comptes administrateurs. Impossible de prendre l'identité d'un autre administrateur, d'un
  compte désactivé ou de soi-même, ni d'enchaîner deux changements d'identité.
- En mode « en tant que », le changement de mot de passe du compte usurpé est interdit et les écrans
  d'administration sont inaccessibles (on a les droits de l'agent, rien de plus).
- **Traçabilité** : le début et la fin sont enregistrés au nom de l'administrateur ; les modifications de
  comptes et les décisions sur les demandes réalisées pendant l'opération sont attribuées à l'administrateur
  avec la mention « en tant que <agent> ».
- Si l'agent n'a pas de compte dans l'application, il apparaît grisé avec le motif.

**Vérifications**
27 tests automatiques passent (recherche et correspondance avec les comptes, repli sans AD, bascule,
droits de l'agent, refus des cas interdits, audit du vrai acteur, retour et déconnexion). La recherche dans
l'AD réel a été essayée avec la clé APM : elle répond et renvoie bien les identifiants. **Non vérifié** :
l'interface (bouton « En tant que… », recherche, bandeau, retour à son compte) a été essayée dans un navigateur sur une instance
de test jetable : elle fonctionne. Non essayé : la bascule vers un vrai agent de l'AD (aucun compte réel n'a été usurpé).

## Étape 6 — Conteneurs Docker et préparation à la DMZ (fait, non exécuté)

**Ce qui a changé**
- **Deux conteneurs**, comme le demande le guide : un **backend** (l'application, servie par un vrai serveur
  de production, gunicorn, et non plus le serveur de développement) et un **frontend** (nginx : il sert les
  écrans et relaie les appels `/api` vers le backend). Lancement : `docker-compose up -d --build`.
- **Le frontend est le seul point d'entrée pour les utilisateurs.** Dans une architecture DMZ, on place uniquement
  le frontend en DMZ (port 8112, même image) et on indique l'adresse interne du backend (`BACKEND_URL`, port 8110).
  Les données restent dans PostgreSQL, en zone interne.
- **Durcissement** : le conteneur backend tourne sans droits d'administrateur ; en-têtes de sécurité
  (anti-clickjacking, politique de contenu stricte sur l'application, pas de mise en cache des écrans) ;
  limitation à 10 tentatives de connexion par minute par adresse au niveau nginx (en plus de celle de
  l'application) ; cookies de session « Secure » par défaut ; l'application refuse de démarrer sans clé
  de session (`CONGES_SECRET_KEY`) au lieu d'en fabriquer une dans un fichier.
- **Supervision** : contrôles de santé des deux conteneurs (`/api/status`, `/healthz`), redémarrage
  automatique, journaux sur la sortie standard (consultables par Portainer ou `docker logs`).
- **Pièces jointes** dans un volume dédié (`conges_data`), hors du code.
- Le fichier `.env.example` a été remis en forme (un commentaire par ligne) pour être lu aussi bien par
  Docker que par l'application. Le `README.md` est mis à jour (démarrage, architecture, sauvegarde).

**Pourquoi**
Le guide impose Docker Compose, un reverse-proxy et une séparation frontend/backend ; la DMZ impose en plus
que le frontend exposé ne détienne aucun secret ni accès direct à la base. Un serveur de production et un
compte non privilégié sont des prérequis de la mise en production.

**Vérifications effectuées**
Les 27 tests passent ; le point d'entrée de production (`wsgi.py`) démarre correctement ; le fichier
`docker-compose.yml` est syntaxiquement valide, et aucun port du backend n'est publié.
**Non vérifié** : Docker n'est pas installé sur ce poste, donc **les images n'ont pas été construites ni
lancées**, et la configuration nginx n'a pas été testée. Un premier essai sur un serveur Docker est
nécessaire (surtout le relais nginx, les cookies derrière HTTPS et l'adresse réelle des clients).

**À décider / valider avec la DSI**
- Les ports sont fixés : backend **8110**, frontend **8111**, futur frontend DMZ **8112**. Le backend n'est publié que sur la machine locale (`BACK_BIND=127.0.0.1`) tant qu'il n'y a pas de frontend DMZ ; il faudra alors l'ouvrir à cette seule adresse par pare-feu.
- Le nombre de reverse-proxys devant l'application (`CONGES_PROXY_HOPS` : 1 si nginx seul, 2 avec le
  proxy de la Ville), sinon l'adresse IP vue (limitations, restrictions des clés API) sera fausse.
- L'adresse publique (`CONGES_BASE_URL`, utilisée dans les liens des mails) et le certificat HTTPS.
- La sauvegarde du volume des pièces jointes.

**Points d'attention restants**
- Les anciens lanceurs `serve.py` et `demarrer-prototype.vbs` (serveur de développement ouvert sur tout le
  réseau) sont obsolètes et ne doivent plus être utilisés ; ils pourront être supprimés.
- Le guide demande Node/Express et React/TypeScript : le backend reste en Python/Flask et le frontend en
  JavaScript simple. Cette réécriture n'a pas été entreprise (voir le plan initial, option 2).

## Complément — Arborescence `backend/` / `frontend/` et frontend DMZ (fait)

**Ce qui a changé**
- Le dépôt suit désormais l'organisation du guide : un dossier **`backend/`** (l'application Python, ses
  migrations, ses tests et son Dockerfile) et un dossier **`frontend/`** (les écrans, la configuration nginx et
  son Dockerfile). Les fichiers ont été déplacés avec Git (l'historique est conservé) et le code lui-même
  n'a pas été modifié ; le fichier de configuration `.env` reste à la racine.
- **Frontend DMZ (port 8112)** : même application, déployable seule sur l'hôte de la DMZ
  (`docker-compose.dmz.yml`), qui relaie vers le backend interne (port 8110). Sa configuration nginx est
  plus restrictive : 5 tentatives de connexion par minute et par adresse, et les routes réservées à l'interne
  sont **invisibles depuis la DMZ** : API `/api/v1` (dont l'administration des clés), documentation Swagger,
  état détaillé, et « se connecter en tant que ».
- Le conteneur backend ne contient plus les écrans : seul le frontend les sert.

**Pourquoi**
Respecter l'organisation du guide, et pouvoir déployer le frontend seul en DMZ sans y exposer ni le code
du backend ni les fonctions d'administration sensibles.

**À valider**
La liste des routes bloquées depuis la DMZ est une proposition prudente : la DRH et la DSI peuvent décider
d'en ouvrir certaines. Le backend devra être joignable depuis l'hôte de la DMZ (port 8110, par pare-feu) et
démarré avec `CONGES_PROXY_HOPS=2` pour connaître la vraie adresse des clients.
**Non vérifié** : comme pour l'étape 6, aucune image n'a pu être construite (Docker absent de ce poste).

## Complément — Numéro de version et journal des versions (version 0.1.0)

**Ce qui a changé**
- L'application porte maintenant un **numéro de version**, **0.1.0**, affiché en haut de l'écran et sur la page de connexion.
  Un clic ouvre le **Journal des versions** : pour chaque version, la date et la liste des nouveautés, en langage métier.
- Convention (la même que l'application delib) : tant que l'application n'est pas en production, la version est de la forme
  **0.x.y** — **x** augmente quand on ajoute un module ou une fonctionnalité, **y** quand on corrige ou améliore sans nouveau module ;
  **1.0.0** sera la version de production.
- **À chaque nouvelle version, la documentation est mise à jour** : le journal des versions (`CHANGELOG.md` et l'écran), le **manifeste
  applicatif** (`MANIFEST.md`, qui décrit toutes les fonctions et règles de l'application), cette note d'explication pour le métier et,
  si besoin, le `README.md`. Un test automatique vérifie que ces documents restent cohérents entre eux, pour qu'aucune version
  ne soit livrée sans documentation. La procédure est écrite dans `CLAUDE.md`.
- Le manifeste (`MANIFEST.md`) est la **référence fonctionnelle** de l'application : rôles et droits, fiche agent, calcul des droits,
  circuit des demandes, heures, tableaux de bord, planning, administration, API, sécurité, questions ouvertes et backlog.

**Pourquoi**
Pour que la DRH et la DSI sachent à tout moment quelle version est en service, ce qu'elle apporte, et que la documentation ne prenne
pas de retard sur l'application.

**Impact pour les utilisateurs**
Un numéro de version discret s'affiche ; rien d'autre ne change.

**Vérifications**
33 tests automatiques passent (dont 6 nouveaux sur le versionnage et son affichage).

## Version 0.2.0 — Paramétrage général, journaux, gabarits d'e-mails et matricule

**Ce qui a changé**
- **Le Paramétrage est maintenant un menu général** avec des sous-sections, comme dans l'application delib : *Calcul et calendrier* (les
  paramètres d'avant), *Utilisateurs*, *Clés API*, *Journal des connexions*, *Mise en page et expéditeur*, *Messages automatiques* et
  *Journal des e-mails*. « Utilisateurs » et « Clés API » ne sont plus des entrées séparées du menu principal pour les administrateurs ;
  les valideurs gardent leur entrée « Utilisateurs » (limitée à leur périmètre).
- **Journal des connexions** : pour chaque connexion, échec, déconnexion ou « se connecter en tant que » : qui, quand, depuis quelle adresse IP,
  avec quel navigateur et quelle méthode (mot de passe local, Active Directory, compte de secours). Recherche, filtres et pagination.
- **Journal des e-mails** : tous les e-mails envoyés ou tentés (destinataire, objet, résultat, texte exact envoyé), avec les raisons d'un
  non-envoi (envoi désactivé, message désactivé, pas d'adresse, erreur de l'API centrale).
- **E-mails paramétrables** : le texte de chaque e-mail automatique (nouvelle demande à valider, relance des demandes en attente, message de
  test) se modifie dans l'application, avec des variables (nom de l'agent, dates, liens…), un aperçu, un envoi de test et un retour au texte
  d'origine. Une **mise en page commune** s'applique à tous les e-mails : nom et adresse de l'expéditeur, en-tête, signature, pied de page.
- **Matricule** : nouveau champ sur les comptes et les fiches agents (unique : on ne peut pas attribuer deux fois le même matricule). Il est visible
  dans l'API et servira de clé pour rapprocher les agents de Sedit RH.
- **Connexion par l'Active Directory** : le bouton « Mot de passe » n'est plus affiché aux agents (leur mot de passe est celui de leur compte
  Ville), la colonne « Mot de passe » de la liste des utilisateurs ne concerne plus que les administrateurs, et la création d'un compte ou
  d'une fiche n'exige ni n'affiche de mot de passe.
- **Sedit RH** : l'adresse et la clé de l'API Sedit RH sont dans le fichier de configuration (`.env`) ; l'application ne l'appelle pas encore
  (voir « À décider »). L'API Sedit RH locale a été lancée et une clé en lecture seule (agents et organisation) a été créée pour SuiviConges.

**Pourquoi**
Regrouper l'administration au même endroit, donner à la DRH la maîtrise du contenu des e-mails sans passer par les développeurs, pouvoir répondre
à « qui s'est connecté et d'où ? » et « quels e-mails sont partis ? » (traçabilité, sécurité, RGPD), éviter de gérer des mots de passe que l'Active
Directory gère déjà, et préparer le rapprochement avec le système RH.

**Impact pour les utilisateurs**
Les agents : le bouton « Mot de passe » disparaît s'ils se connectent par l'Active Directory. Les administrateurs : les écrans Utilisateurs et Clés API
sont désormais sous Paramétrage. Les journaux sont conservés **365 jours** par défaut (réglable de 30 à 3 650 jours) puis purgés automatiquement.

**Vérifications**
41 tests automatiques passent (journaux, gabarits, aperçu, envoi de test simulé, matricule, mot de passe en mode AD, version). Les écrans ont été essayés
dans un navigateur sur une instance de test jetable (menu, journal des connexions avec une connexion réussie et une échouée, messages automatiques avec
aperçu, liste des utilisateurs). **Non vérifié** : envoi réel d'un e-mail par l'API centrale (envoi désactivé pour l'instant), saisie du
matricule dans la fiche à l'écran, usage de la clé Sedit RH depuis l'application.

**À décider**
- Que doit faire l'application avec Sedit RH : pré-remplir la fiche d'un agent à partir de son matricule, synchroniser les agents et l'organisation,
  contrôler les arrivées et départs ? (Q13 du manifeste.)
- Quels autres e-mails automatiques souhaite-t-on (validation ou refus à l'agent, annulation, alerte d'expiration des heures de récupération) ?
- La clé Sedit RH actuelle est une clé de développement sur l'API locale ; la clé et l'adresse de production restent à obtenir.

## Version 0.2.1 — E-mails : activation dans l'application, tests toujours possibles, écran en liste

**Ce qui a changé**
- **L'envoi automatique des e-mails s'active dans l'application** (Paramétrage > E-mails, case à cocher), plus dans le fichier de configuration. Il est désactivé par défaut.
- **Les messages de test partent même si l'envoi est désactivé** (il suffit que l'API centrale de la Ville soit configurée) : on peut donc vérifier les messages avant d'activer l'envoi.
- **Messages automatiques** : la liste des messages est à gauche ; un clic affiche leur contenu à droite pour le voir ou le modifier. La **liste des variables** (avec leur signification) est affichée à côté du texte, et chaque variable s'insère d'un clic.
- **L'aperçu ne montre que le message.** L'en-tête et le pied de page sont ajoutés par l'API centrale de la Ville : ils ne sont donc pas prévisualisés.
- **L'en-tête propre à l'application est retiré** : l'API centrale n'accepte que l'**expéditeur** et le **pied de page** comme paramètres, son en-tête est un gabarit institutionnel fixe (voir Q15 du manifeste). L'écran devient « Expéditeur et pied de page ».

**Pourquoi**
Ce que la DRH règle doit se faire dans l'application, et la mise en forme doit rester celle de la Ville (un seul en-tête, pas deux).

**Impact pour les utilisateurs**
Aucun pour les agents. Les administrateurs retrouvent l'envoi des e-mails désactivé tant qu'ils ne cochent pas la case ; ce qui était saisi comme titre ou couleur d'en-tête n'existe plus.

**Vérifications**
43 tests automatiques passent (activation par l'administrateur, test envoyé alors que l'envoi est désactivé, aperçu sans en-tête ni pied de page, en-tête refusé). Les écrans (liste des messages, changement de message, case d'activation) ont été essayés dans un navigateur sur une instance de test jetable.
**Non vérifié** : envoi réel d'un e-mail par l'API centrale.

## Version 0.2.2 — Déploiement Docker : sous-réseau fixe configurable

**Ce qui a changé**
- Le déploiement Docker déclare maintenant un **sous-réseau fixe** pour l'application (`10.77.110.0/24` par défaut, `10.77.112.0/24` pour le frontend DMZ), modifiable dans le `.env` (`CONGES_SUBNET`, `CONGES_DMZ_SUBNET`).

**Pourquoi**
Sur le serveur `docker-apps`, le démarrage échouait avec « all predefined address pools have been fully subnetted » : les plages d'adresses automatiques de Docker étaient toutes utilisées par les autres applications, et Docker ne pouvait plus créer de réseau pour celle-ci.

**Impact pour les utilisateurs**
Aucun. Si la plage choisie chevauche un réseau existant, Docker le signale au démarrage : il suffit alors de changer la valeur dans le `.env`.

**Vérifications**
La syntaxe des deux fichiers `docker-compose` a été contrôlée et les tests passent. **Non vérifié** : le démarrage sur le serveur (Docker n'est pas disponible sur le poste de développement).

## Version 0.2.3 — E-mails : adresse du test d'envoi

**Ce qui a changé**
- Le bouton de test d'envoi des messages automatiques s'accompagne d'un **champ « Envoyer un test à »** où l'on saisit l'adresse qui recevra le message. L'adresse saisie est **mémorisée** dans le navigateur pour les tests suivants (même chose sur l'écran « Expéditeur et pied de page »).

**Pourquoi**
Le test utilisait l'adresse e-mail du compte de l'administrateur et affichait une demande d'adresse sans indiquer où la saisir, alors que ce compte n'en a pas.

**Impact pour les utilisateurs**
Aucun, hors écran Paramétrage > E-mails.

**Vérifications**
43 tests automatiques passent ; l'écran a été essayé dans un navigateur sur une instance de test jetable.

## Version 0.3.0 — Test de l'API Sedit RH et nombre d'agents

**Ce qui a changé**
- Un **nouveau menu** « Intégrations > API Sedit RH » dans le Paramétrage. Il affiche l'adresse configurée et si la clé est renseignée (jamais la clé elle-même), et propose un bouton **« Tester la connexion et compter les agents »**.
- Le test indique si la connexion fonctionne (avec le temps de réponse), le **nombre d'agents en poste** et leur **répartition par statut** (titulaires, contractuels, stagiaires…). En cas de problème, la cause est expliquée : API non configurée, injoignable, clé refusée, droit manquant.

**Pourquoi**
Vérifier simplement, depuis l'application, que la liaison avec le système RH fonctionne, avant de s'en servir (rapprochement par matricule, pré-remplissage des fiches). Le nombre d'agents sert de première valeur de contrôle.

- **Correction d'affichage** découverte pendant les essais : dans toute l'application, un bouton principal (orange) devenait illisible quand la souris le survolait (texte blanc sur fond clair) ; c'est corrigé.

**Respect des données personnelles**
Le nombre est lu dans les **effectifs agrégés** de Sedit RH : l'application ne lit, n'affiche et n'enregistre **aucune donnée d'agent** pour ce test.

**À savoir**
La clé de l'application doit porter le droit « effectifs:read ». Sur l'API Sedit RH locale de développement, j'ai ajouté ce droit à la clé créée pour SuiviConges ; en production, il faudra le demander lors de la création de la clé. Le `.env.example` le précise.

**Vérifications**
45 tests automatiques passent (comptage, repli sur la somme, clé jamais renvoyée, droits administrateur, erreurs expliquées : non configuré, 401, 403, réseau). L'écran a été essayé dans un navigateur contre l'API Sedit RH locale.

## Version 0.4.0 — Organisation Sedit RH, matricules et création d'agents

**Ce qui a changé**
- **Matricules des agents de la base** : un écran *Paramétrage > Intégrations > Matricules* retrouve, dans Sedit RH et par nom et prénom, le matricule des agents déjà présents dans l'application. Seules les correspondances **certaines** sont proposées ; l'administrateur coche ce qu'il applique. Les homonymes et les agents introuvables sont signalés et jamais modifiés.
  **Appliqué à la base actuelle : 30 agents sur 34 ont maintenant leur matricule** ; les 4 autres sont introuvables dans Sedit RH (à saisir à la main dans Utilisateurs, ou à vérifier : agent parti, orthographe différente).
- **Organisation RH** : un écran *Paramétrage > Intégrations > Organisation RH* présente l'organisation de Sedit RH sous forme d'arborescence **Direction › Service › Secteur › Agent**, comme la hiérarchie de l'application, avec le nombre d'agents, ceux qui sont déjà dans l'application, et le compte valideur correspondant à chaque unité. Recherche, filtres, actualisation.
- **Création d'agents depuis la base RH** : on coche des agents, un secteur, un service ou une direction entière, puis « Créer les agents sélectionnés ». Un **aperçu** montre ce qui sera créé (rien n'est écrit à ce stade), puis la création crée les **comptes** et les **fiches** avec le matricule de Sedit RH. Les comptes valideurs manquants de l'organisation (direction, service, secteur) peuvent être créés automatiquement ; l'**e-mail** et l'**identifiant** de connexion sont cherchés dans l'annuaire Active Directory quand le nom correspond à un seul compte.

**Pourquoi**
Éviter de ressaisir à la main les agents et leur organisation, rapprocher durablement l'application du système RH grâce au matricule, et pouvoir peupler l'application service par service.

**Respect des données personnelles**
La liste des agents de Sedit RH n'est lue qu'à la demande de l'administrateur, conservée quelques minutes en mémoire et **jamais copiée** : seuls les agents que l'on choisit de créer ou de rapprocher sont enregistrés (identité, matricule). Tout est réservé aux administrateurs et inscrit au journal d'audit.

**À savoir / à décider**
- Les agents créés n'ont pas encore leurs paramètres de calcul (pénibilité, durée hebdomadaire, quotité) : Sedit RH ne les fournit pas. La date d'arrivée n'est reprise que si elle tombe dans l'année de la fiche.
- Les **comptes d'unité** créés automatiquement sont des comptes structurels (sans titulaire) : il faut ensuite les attribuer à leurs responsables, en leur donnant un identifiant AD.
- Un agent sans e-mail dans l'annuaire est créé sans e-mail (à renseigner dans sa fiche). Faut-il plutôt le refuser ? (Q16 du manifeste.)
- Le rapprochement se fait par nom et prénom : deux agents de même nom ne sont jamais rapprochés automatiquement.

**Vérifications**
49 tests automatiques passent (rapprochement certain / ambigu / introuvable, application sans écrasement, arbre avec niveaux fusionnés, création des comptes d'unité et des agents, réutilisation des comptes existants, idempotence, droits administrateur, erreurs de Sedit RH). Les trois écrans ont été essayés dans un navigateur contre l'API Sedit RH réelle, sur une base de test jetable (3 rapprochements, aperçu et création de 16 agents d'une direction avec ses 4 comptes d'unité), puis supprimée.

## Version 0.5.0 — Trois rôles et création d'une personne depuis Sedit RH et l'Active Directory

**Ce qui a changé**
- **Deux rôles, plus un droit** : Valideur et Agent ; **Administrateur** n'est plus un rôle mais une case à cocher qui s'ajoute à celui d'un agent ou d'un valideur (une même personne peut être valideur *et* administrateur). Les anciens niveaux (DGS, DGA, Direction, Service, Secteur, Unité, Équipe) deviennent tous « Valideur » à l'écran ; leur niveau reste connu en interne, donc **rien ne change** pour les droits, les périmètres et les validations existants.
- **Formulaire « Nouvelle personne »** (Paramétrage > Utilisateurs) : on tape un nom, un prénom ou un matricule, l'application propose les agents de Sedit RH ; en cliquant, nom, prénom, matricule et unité sont repris. L'Active Directory est ensuite interrogé pour trouver l'**e-mail** et l'**identifiant** (exemple : Christophe PARISI → cparisi) ; s'il y a plusieurs comptes possibles, on choisit.
- **Agent** : on choisit son **unité** (direction, service, secteur ou équipe de Sedit RH) ; il est rattaché automatiquement au valideur de cette unité (ou de l'unité supérieure la plus proche) et sa fiche est créée.
- **Valideur** : on choisit son unité **et l'unité qui le valide** (forcément supérieure à la sienne). Pour un valideur de niveau **Direction**, c'est un **DGA** qui valide : le formulaire liste les DGA/DGS existants ; un DGA ou un DGS se crée avec le « niveau de validation » correspondant (sans unité).

**Pourquoi**
Ne plus ressaisir les agents, partir de la source RH (Sedit RH) et de l'annuaire (AD), et rattacher chacun à l'organisation officielle plutôt qu'à des comptes saisis à la main.

**À savoir / à décider**
- Il faut qu'un valideur existe pour l'unité (ou une unité supérieure) avant de créer des agents dedans : sinon l'application le dit et propose de créer d'abord le valideur. Les comptes d'unité créés avant cette version (DIR-…, SRV-…) sont reconnus par leur nom ; faut-il les remplacer par de vraies personnes ? (Q17 du manifeste.)
- Les unités sont lues dans Sedit RH à la première utilisation, puis sur demande de l'administrateur ; elles ne contiennent aucune donnée personnelle.

**Vérifications**
54 tests automatiques passent (recherche Sedit RH à plusieurs mots, rapprochement AD unique / plusieurs / aucun, création d'agent et de valideur, unité validatrice non supérieure refusée, droits, profil à trois valeurs). Vérifié dans un navigateur sur une instance jetable : recherche « christophe parisi », e-mail et identifiant trouvés dans l'AD, unité reprise, création d'un valideur puis d'un agent rattaché automatiquement. **Non fait** : migration des comptes d'unité hérités vers des personnes ; essai avec un valideur non administrateur dans le navigateur (couvert par les tests).

## Version 0.6.0 — Mes agents (glisser-déposer) et règles métier consultables

**Ce qui a changé**
- **Menu « Mes agents »** : à gauche, l'arbre des personnes que je valide, puis de celles que mes subordonnés valident, etc. À droite, la liste des agents de **Sedit RH de mon niveau ou en dessous** qui ne sont pas encore dans l'application. On **glisse un agent sur une personne** : il est créé dans l'application sous elle (compte, fiche, matricule, e-mail et identifiant cherchés dans l'AD) et on confirme son **unité**.
- **Exemple** : on glisse Isabelle ABBAS sous Marc CHEVALIER (et on définit son unité), puis Florian BRUN sous Isabelle ABBAS : Isabelle devient automatiquement **valideur** de Florian et de l'unité de Florian (si elle n'avait pas d'unité, elle prend la sienne).
- On peut aussi glisser une personne déjà présente sur un autre valideur pour la **déplacer** (sa fiche suit).
- **Règles métier** : toutes les règles de l'application sont rassemblées dans un document, lisible dans *Paramétrage > Documentation > Règles métier*. Il est mis à jour à chaque version (règle inscrite dans les instructions du projet).

**Pourquoi**
Construire l'organisation « à la souris » à partir de la source RH, sans formulaire, et garder une référence unique et lisible des règles.

**À savoir / à décider**
- Si la personne qui reçoit un agent est un simple agent, elle devient valideur : son niveau interne est celui de son unité, mais jamais au niveau de son propre valideur (il est abaissé d'un cran si besoin).
- Un agent peut être glissé sous une personne dont l'unité ne le couvre pas ; faut-il l'interdire ? (Q18 du manifeste.)

**Vérifications**
58 tests automatiques passent (arbre, liste Sedit RH limitée au périmètre, création par glisser-déposer avec promotion en valideur, refus hors périmètre / doublon, déplacement et refus des cycles, document de règles servi). Vérifié dans un navigateur sur une instance jetable : Isabelle ABBAS déposée sous Marc CHEVALIER puis Florian BRUN sous Isabelle (devenue « Valideur »), e-mails trouvés dans l'AD, écran des règles métier. **Non fait** : glisser-déposer à la souris réelle (les événements ont été simulés par script) ; essai avec un valideur non administrateur dans le navigateur (couvert par les tests).

## Version 0.6.1 — Connexion : identifiant insensible à la casse

**Ce qui a changé** : « machevalier » et « MCHEVALIER » désignent désormais le même compte à la connexion.

**Pourquoi** : le compte recréé depuis Sedit RH s'appelle `MCHEVALIER` (majuscules), alors que l'identifiant de l'annuaire est `machevalier` ; la connexion répondait « identifiant incorrect » alors que le mot de passe AD était bon.

**Vérifications** : test automatique (saisie en minuscules, en majuscules, identifiant inconnu). Le compte `machevalier` d'origine avait été supprimé et recréé sous `MCHEVALIER` (visible au journal d'audit) ; aucune autre donnée n'a été modifiée.

## Version 0.6.2 — Mes agents : sélection multiple

**Ce qui a changé** : dans « Mes agents », on peut cocher plusieurs agents de Sedit RH (ou « Tout sélectionner ») et les glisser **en une seule fois** sur une personne. Ils sont tous créés sous elle, chacun dans son unité Sedit RH (ou dans une unité commune si on en choisit une). La sélection survit aux recherches.

**Pourquoi** : créer une équipe entière sans répéter le glisser-déposer agent par agent.

**Vérifications** : essai dans un navigateur sur une instance jetable : trois agents cochés (Isabelle ABBAS, Florian BRUN, Thibault CONTAMINE), glissés d'un coup sous Marc CHEVALIER, les trois créés (e-mails trouvés dans l'AD). Le geste de souris réel n'a pas pu être rejoué (événements simulés par script).

## Version 0.7.0 — Fiche congés = première période, agents hors unité, jours hors période grisés

**Ce qui a changé**
- **La fiche naît avec la première période de paramètres.** Dans « Mes agents », un agent glissé est d'abord une personne (compte). Le bouton **« Définir la période »** (pénibilité, durée, quotité, jours/semaine, comme dans la fiche) crée sa fiche congés de l'année, puis un lien « Fiche 2026 » l'ouvre. « Mes fiches » ne montre donc que les agents sous ma responsabilité qui ont au moins une période.
- **Agents hors de mon unité** : une case « Inclure les agents hors de mon unité (toute la collectivité) » complète la liste de droite (par défaut, seulement mon unité et en dessous).
- **Calendrier** : les jours qui ne sont couverts par aucune période (avant l'arrivée, après le départ — par exemple après un départ au 31/08) sont **grisés et non sélectionnables**, et une demande d'absence sur ces jours est refusée.

**Pourquoi**
Ne créer une fiche que lorsqu'elle est exploitable (droits calculables), et empêcher de poser des congés en dehors de la présence de l'agent.

**À savoir / à décider**
- Les fiches déjà existantes sans période (par exemple importées) restent visibles ; leur ligne de « Mes agents » propose « Compléter la période ».
- Un agent d'une autre direction peut être placé sous une personne de mon périmètre : il apparaît alors dans mon arbre, mes fiches et mon planning (Q18 du manifeste : faut-il le restreindre ?).
- Les jours déjà saisis hors période restent affichés mais ne sont plus sélectionnables.

**Vérifications**
60 tests automatiques passent (création sans fiche, première période validée contre les listes, refus d'une période en double, agents hors unité, couverture du calendrier). Vérifié dans un navigateur sur une instance jetable : glisser, « Définir la période », fiche créée, départ au 31/08 → 244 demi-journées grisées et clic refusé, case « toute la collectivité » (2 428 agents). **Non fait** : geste de souris réel (glisser simulé par script) ; essai avec un valideur non administrateur dans le navigateur.

## Version 0.8.0 — Jours travaillés par période, entités dans « Mes fiches », noms corrigés

**Ce qui a changé**
- **Jours travaillés** : chaque période de paramètres comporte désormais les jours travaillés (cases L M M J V S D ; lundi-vendredi par défaut) et une case « fériés travaillés ». Le nombre de jours par semaine suit les cases cochées. La même saisie est proposée à la création de la première période (Mes agents > Définir la période).
- **Calendrier** : les jours non travaillés sont **grisés et non sélectionnables** ; une absence posée sur une période longue ne les compte donc pas. Le serveur refuse aussi toute demande qui les contient. Le tableau des périodes est resserré pour tenir sans défilement.
- **Mes fiches** : les groupes portent le **nom de l'entité** (et non celui du valideur) ; le **responsable valideur** est affiché en premier dans le groupe de son entité.
- **Correction de noms** : le nom et le prénom étaient restés collés dans deux fiches créées depuis Sedit RH (« BOUATOU FAROUK », « CHEVALIER MARC ») ; ils sont séparés et le défaut est corrigé pour les prochaines fiches. Données corrigées sur la base actuelle : 2 fiches et 3 comptes.

**Pourquoi**
Calculer correctement les jours posés pour un agent qui ne travaille pas tous les jours, et présenter les fiches par entité plutôt que par personne.

**À savoir / à décider**
- Par défaut, toutes les fiches existantes sont considérées comme travaillant du lundi au vendredi, jours fériés non travaillés : leurs samedis, dimanches et jours fériés sont donc désormais grisés. Les absences déjà saisies sur ces jours restent affichées.
- Les moteurs de calcul des droits (CA, RTT…) ne changent pas : les jours travaillés servent à la sélection et au décompte des demandes.

**Vérifications**
60 tests automatiques passent (jours travaillés, fériés, effectif des cases cochées, nom et prénom repris de Sedit RH). Vérifié dans un navigateur sur une instance jetable : agent à 4 jours (lundi-jeudi, fériés travaillés) → vendredi, samedi et 1er mai grisés ; tableau des périodes sans défilement ; « Mes fiches » avec l'entité en titre et la responsable en premier. **Non fait** : décompte d'une période longue à la souris (couvert par la sélection qui ignore les jours grisés).

## Version 0.8.1 — Fiches : « Valideur » et noms Prénom NOM

**Ce qui a changé** : le mot « Propriétaire » est remplacé par « Valideur » sur les fiches (cartes, en-tête de fiche, tableau de bord, changement de valideur), et la personne est affichée par son **prénom et son nom** (Marc CHEVALIER) au lieu de son identifiant de connexion (MACHEVALIER).

**Pourquoi** : le « propriétaire » d'une fiche est en réalité son valideur, et l'identifiant AD n'est pas parlant pour les utilisateurs.

**À savoir** : les comptes d'unité anciens (Direction RH…) gardent leur nom d'unité faute de prénom ; l'écran d'import RH de l'administration garde son vocabulaire d'origine. La clé « proprietaire » de l'API externe /api/v1 n'est pas modifiée.

**Vérifications** : 60 tests automatiques passent ; libellés vérifiés dans le code des écrans concernés. Non revu à l'écran dans le navigateur.

## Version 0.9.0 — Menu « Mes congés » et « Mon équipe »

**Ce qui a changé**
- Nouveau menu **« Mes congés »** : chacun y voit sa propre fiche de congés (calendrier, soldes, demandes) sans le bloc « Paramètres et périodes », qui reste du ressort du valideur. Sans fiche, un message explique qu'elle est créée quand le valideur définit la période.
- Le menu **« Mes agents »** devient **« Mon équipe »** (écran, documentation, règles métier).
- Pour un agent, le menu « Mes fiches » (qui ne montrait que sa fiche) est remplacé par « Mes congés ».

**Pourquoi** : donner à chacun un accès direct et simple à ses propres congés, et séparer ce qui relève de l'agent (ses congés) de ce qui relève du valideur (les paramètres et l'équipe).

**Vérifications** : tests automatiques (60) et essai dans un navigateur sur une instance jetable (voir ci-dessous).

## Version 0.9.1 — E-mails des valideurs

**Ce qui s'est passé** : une demande faite « en tant que » Farouk BOUATOU n'a pas prévenu son valideur Marc CHEVALIER. Le journal des e-mails l'explique : « Le valideur CHEVALIER MARC n'a pas d'adresse e-mail ». Son compte avait été créé avec l'annuaire, qui contient deux comptes MARC CHEVALIER (un compte de test sans messagerie et le vrai) : l'application n'avait pas osé choisir.

**Ce qui a changé**
- L'adresse de Marc CHEVALIER (`machevalier@ivry94.fr`) et son identifiant AD ont été renseignés sur son compte.
- Désormais, à nom égal, la création d'une personne retient le compte de l'annuaire qui a une adresse e-mail.
- Dans « Mon équipe », une pastille « ⚠ e-mail » signale les personnes sans adresse.

**À décider** : 15 comptes actifs non agents n'ont pas d'e-mail, notamment des comptes d'unité anciens (CONG-BC « Direction RH », CONG-BE…) : leurs agents ne préviennent donc personne. Faut-il les rattacher à de vraies personnes, ou faire remonter la notification au premier valideur de la chaîne qui a une adresse ? (Q17 du manifeste.)

**Vérifications** : 60 tests automatiques passent (choix du compte avec messagerie) ; l'envoi lui-même n'a pas été rejoué.

## Version 0.10.0 — Mon équipe par défaut, « Voir tout » pour les administrateurs, recherche AD

**Ce qui a changé**
- **Périmètre** : dans Mes fiches, Mon équipe, Demandes, Planning et les tableaux de bord, **tout le monde voit son équipe**, administrateurs compris. Les administrateurs ont un interrupteur **« Voir tout »** dans la barre du haut (mémorisé dans le navigateur) pour voir toute la collectivité.
- **Agents** : sans droit d'administration, ils ne voient ni « Mes fiches » ni « Mon équipe » ; ils utilisent « Mes congés », « Mes demandes » et le planning.
- **Recherche AD** : un bouton sur les personnes sans e-mail dans « Mon équipe » cherche leur compte dans l'Active Directory (par le nom, ou en tapant autre chose) et reprend l'adresse e-mail et l'identifiant.

**Pourquoi** : un administrateur qui valide une équipe veut d'abord voir cette équipe ; et les valideurs doivent pouvoir réparer eux-mêmes une adresse e-mail manquante, qui bloque les notifications.

**À savoir** : un administrateur qui n'a personne sous sa responsabilité ne voit rien tant que « Voir tout » n'est pas coché. L'accès direct à une fiche par son lien, et l'écran Utilisateurs de l'administration, ne changent pas.

**Vérifications** : 61 tests automatiques passent (périmètre par défaut et « Voir tout », refus de l'élargissement par un non-administrateur, recherche AD et rattachement). Non essayé à l'écran dans le navigateur.

## Version 0.10.1 — Mes congés : sa propre fiche même pour un valideur

**Ce qui s'est passé** : en agissant en tant que Farouk BOUATOU (valideur de son service, avec une fiche de congés), « Mes congés » annonçait qu'il n'avait pas de fiche. La liste des fiches d'un valideur ne contient que celles de son équipe, or sa propre fiche appartient à son propre valideur.

**Correction** : « Mes congés » demande désormais directement sa propre fiche à l'application, sans passer par la liste de l'équipe.

**Vérifications** : test automatique (valideur dont la fiche est hors de son équipe) ; 62 tests passent. Non rejoué à l'écran avec « en tant que ».

## Version 0.10.2 — Planning : jours non validés en pointillé

**Ce qui a changé** : dans le planning, les jours d'une demande encore en attente de validation s'affichent comme dans la fiche : couleur éclaircie, contour en pointillé et info-bulle. Les jours validés gardent leur couleur pleine.

**Pourquoi** : le planning montrait les demandes en attente avec la même couleur que les congés validés (seul un fin pointillé les distinguait).

**Vérifications** : 62 tests automatiques passent ; syntaxe du script vérifiée. Non vérifié à l'écran (il faut une demande en attente, comme celle de BOUATOU).

## Version 0.11.0 — E-mails avec boutons, délégation des valideurs, Mon équipe en deux niveaux

**Ce qui a changé**
- **E-mail de demande** : les dates sont données en plages (« du 20 avril 2026 au 24 avril 2026 », sans compter les week-ends manquants ; « (après-midi) » ou « (matin) » aux extrémités si besoin). Trois boutons : **Valider**, **Refuser** et **Voir le calendrier d'équipe**.
- **Valider / Refuser depuis l'e-mail** : le bouton ouvre une page de confirmation (sans connexion) qui rappelle la demande ; **rien n'est enregistré tant qu'on n'a pas cliqué** sur Valider ou Refuser, et les mêmes contrôles que dans l'application s'appliquent (droits, solde). Le lien est personnel et valable 14 jours.
- **Délégation** (nouveau menu) : je délègue à mon valideur automatiquement quand je suis absent, et/ou sur des périodes du/au (même sans congés) ; il reçoit alors aussi les mails de demande (avec les boutons) et les relances ; je vois les validations faites à ma place.
- **Mon équipe** : par défaut, seulement les personnes que je valide directement (et celles de mon délégant le temps d'une délégation) ; le bouton « Voir toute ma ligne hiérarchique » ajoute celles que mes agents valident, et ainsi de suite.

**Pourquoi** : valider en un clic depuis sa messagerie, voir d'un coup d'œil qui est absent dans son équipe, et ne pas bloquer les demandes quand un valideur est absent.

**À savoir / à décider**
- Quiconque détient le lien d'un e-mail peut décider au nom de son destinataire (comme tout lien à jeton) : il ne faut pas transférer ces e-mails. Faut-il exiger l'authentification AD sur la page de confirmation ? (Q19 du manifeste.)
- Le délégataire est toujours le responsable direct du valideur ; il pouvait déjà valider (règle hiérarchique) : la délégation le prévient et trace ce qu'il fait.
- L'adresse des liens vient de `CONGES_BASE_URL` : elle doit être celle du site public (le frontal relaie `/api`) ; sans elle, les boutons n'apparaissent pas.
- Les e-mails n'ont pas été envoyés réellement ici ; le texte par défaut du message « nouvelle demande » est mis à jour automatiquement s'il n'avait pas été personnalisé.
- Dans « Mes congés », une demande posée par un administrateur ou un valideur suit la même règle que pour tout agent : elle part à son propre valideur (personne ne valide sa propre demande).

**Vérifications** : 65 tests automatiques passent (plages de dates, boutons, page de confirmation sans effet avant clic, refus pour un compte non habilité, décision tracée, délégation par période et automatique, validations faites à ma place, arbre direct / ligne hiérarchique). Vérifié dans un navigateur sur une instance jetable : écran Délégation (période, case automatique, bandeau « délégation en cours »), Mon équipe direct puis ligne hiérarchique. **Non vérifié** : réception réelle d'un e-mail et clic sur ses boutons, relance d'un délégataire.

## Version 0.11.1 — Onglets de fiches : « + » ouvre des fiches de l'équipe

**Ce qui a changé** : le « + » de la barre d'onglets (au-dessus des fiches) n'ouvrait que la création d'une nouvelle fiche. Il affiche désormais la liste des agents sous ma responsabilité, avec une recherche et des cases à cocher ; les fiches cochées s'ouvrent chacune dans son onglet. Les fiches déjà ouvertes sont grisées.

**Pourquoi** : retrouver rapidement plusieurs fiches de l'équipe sans repasser par la liste. La création d'une fiche reste possible dans « Mes fiches » et « Mon équipe » (« Définir la période »).

**Vérifications** : syntaxe vérifiée, 65 tests automatiques passent. **Non essayé à l'écran** dans le navigateur.

## Version 0.11.2 — Fiche plus compacte ; « Mes congés » en consultation

**Ce qui a changé**
- L'en-tête de la fiche tient en **une seule ligne de champs** (e-mail, matricule, valideur, responsable d'unité, reliquat, solde CET) avec les boutons d'heures en ligne ; les trois cartes et leurs titres disparaissent.
- Dans **Mes congés**, les informations ne sont plus modifiables : champs grisés, pas de bouton Supprimer ni « Changer le valideur ». On consulte sa fiche et on pose ses demandes.

**À savoir** : cette protection est celle de l'écran « Mes congés » ; un administrateur qui ouvre sa propre fiche par « Mes fiches » garde ses droits de modification habituels.

**Vérifications** : essai dans un navigateur sur une instance jetable (champs actifs en fiche normale, tous désactivés en mode Mes congés, bloc des périodes masqué) ; 65 tests automatiques passent. Je n'ai pas mesuré la hauteur gagnée sur votre écran.

## Version 0.11.3 — Tableau de bord RH : entités et responsables

**Ce qui a changé** : dans « Absences par direction / service », la DSI est présentée comme la DRH : les groupes portent le **nom de l'entité** (par exemple « DIRECTION DES SYSTEMES D'INFORMATION ») et non celui de la personne (« CHEVALIER MARC »). Le **responsable** de l'entité est la première ligne de sa liste, avec « (Responsable) ». Les entités de même nom (la direction et son service du même nom, ou deux valideurs de la même unité) sont regroupées en une seule ligne. Le tableau « par direction / service » utilise les mêmes noms.

**Vérifications** : test automatique (nom d'entité, responsable en premier) ; 66 tests passent. Non revu à l'écran sur vos données réelles.

## Version 0.11.4 — Mon équipe : Dupliquer pour l'année suivante

**Ce qui a changé** : dans « Mon équipe », chaque personne qui a une fiche affiche, à côté de « Fiche 2026 », un bouton **« Dupliquer pour 2027 »** (année N+1 par rapport à l'année choisie en haut). Il crée la fiche de l'année suivante avec les mêmes paramètres ; les congés posés et les dates d'arrivée / de départ ne sont pas copiés. Une fois la fiche créée, le bouton est remplacé par « ✓ 2027 ».

**À savoir** : j'ai placé ce bouton dans « Mon équipe », sur la ligne de chaque personne, à côté du lien de la fiche. La duplication en série existe toujours dans « Mes fiches ». Dites-moi si vous parliez d'un autre écran.

**Vérifications** : test automatique (bouton proposé, duplication, puis « existe déjà ») ; 66 tests passent. Non essayé à l'écran.

## Version 0.11.5 — Mes congés : demandes pour tous, jamais de validation directe

**Ce qui s'est passé** : pour un administrateur, la fiche « Mes congés » n'offrait pas la pose de demandes (l'administrateur était considéré comme pouvant saisir directement, donc la fiche restait en lecture seule), et ses demandes d'heures et de cassage étaient validées d'office.

**Ce qui a changé** : sur sa propre fiche, **tout le monde — administrateur compris — pose des demandes** (jours, heures, cassage) qui vont à son valideur ; à défaut d'un valideur actif, à un autre administrateur ; sans personne au-dessus, la demande est validée d'office (cas d'un administrateur seul). Personne ne saisit ni ne valide directement ses propres congés. Un autre administrateur ou le valideur peut toujours saisir directement sur la fiche d'un agent.

**Vérifications** : test automatique (administrateur sur sa propre fiche : demande, pas de saisie directe ; un autre administrateur saisit ; son valideur est désigné) ; 67 tests passent. Non essayé à l'écran.

## Version 0.12.0 — Mon équipe remplace Mes fiches

**Ce qui a changé**
- **Une seule vue** : « Mes fiches » disparaît du menu, « Mon équipe » la remplace.
- **Par entité** : les personnes sont classées sous le nom de leur entité (unité Sedit RH), le responsable ★ en premier ; les entités de même nom sont regroupées.
- **Période en images** : chaque carte montre la quotité en camembert (100 %, 80 %…), les jours travaillés (L M M J V S D) en couleur, la durée hebdomadaire et la pénibilité ; « F » si l'agent travaille les jours fériés ; « n périodes » s'il y en a plusieurs (la période en cours est affichée).
- **Actions conservées** : ouvrir la fiche, « + Nouvelle fiche » et « Dupliquer toutes les fiches pour 2027 » en haut de page, « Dupliquer pour 2027 » par personne, Définir la période, Recherche AD, glisser-déposer pour changer de valideur (sur une carte ou sur le titre d'une entité).

**À savoir** : la sélection par cases à cocher et la duplication « de la sélection » de l'ancien Mes fiches n'existent plus ; la duplication se fait par personne ou pour toute l'équipe. Les anciens liens « Mes fiches » ouvrent Mon équipe.

**Vérifications** : essai dans un navigateur sur une instance jetable (groupes par entité, camemberts 100 % et 80 %, jours travaillés, boutons) ; 67 tests automatiques passent. Non vérifié : glisser à la souris réelle d'une carte, rendu sur de grandes équipes.

## Version 0.12.1 — Fiche : unité modifiable, e-mail et matricule verrouillés

**Ce qui a changé**
- **E-mail et matricule** : non modifiables dans la fiche (ils viennent de l'annuaire et de Sedit RH), y compris côté serveur une fois renseignés. Pour un e-mail manquant : « Recherche AD » dans Mon équipe.
- **« Resp. unité »** : la case est retirée. Le responsable d'une entité est son valideur (★, premier de la liste dans Mon équipe). Les anciennes marques « responsable » restent en base mais ne se modifient plus.
- **Unité** : un champ dans la fiche permet de choisir une autre unité pour l'agent, dans la liste de **toutes les unités de sa direction**. Pour la DSI : la direction (BF), la DSI (BF1), Infrastructure réseaux systèmes (BF6) et son secteur Architecture réseaux (BF62), Bureau des projets (BF8), Déploiement et support (BF9). Changer l'unité ne change pas son valideur.
- **Mon équipe** : colonne des personnes plus large, liste Sedit RH plus étroite.

**À savoir** : sur les fiches existantes, un matricule ou un e-mail déjà saisi à la main et erroné ne peut plus être corrigé depuis la fiche (la correction passe par la source : Sedit RH, annuaire). La mention « (Responsable) » du planning et du tableau de bord reste liée aux anciennes marques.

**Vérifications** : test automatique (liste des unités de la direction, refus d'une autre direction, verrouillage e-mail / matricule) ; 68 tests passent ; essai navigateur sur instance jetable (champs désactivés, 6 unités de la DSI proposées, colonnes 1099 / 330 px).

## Version 0.13.0 — Années dans la fiche, report des périodes, équipes manquantes

**Ce qui a changé**
- **Passer à la fiche 2027** : dans la fiche, le sélecteur d'année (à droite du nom) liste les années de la personne ; « + 2027 (reporter la période) » prépare l'année suivante.
- **On reporte des périodes, pas des fiches** : la fiche 2027 est créée avec la période en vigueur en fin 2026 (quotité, durée, pénibilité, **jours travaillés**, jours fériés) sur toute l'année. Avant, la duplication perdait les jours travaillés ; elle est corrigée et refuse de créer une fiche qui existe déjà. Les boutons de Mon équipe s'appellent désormais « Reporter en 2027 ».
- **Équipe de la DSI** : vous aviez raison. Sedit RH ne publie pas dans son organisation l'**« Équipe projet éduc. innovation inclusion »** (code BF1112, 2 agents de la DSI) : elle n'apparaissait donc pas dans la liste des unités. La liste est maintenant complétée par les équipes portées par des agents (62 unités ajoutées, dont BF1112 rattachée à la DSI), et déjà actualisée sur la base actuelle (281 → 343 unités). Il n'existe pas d'« équipe numérique éducatif » sous ce nom dans Sedit RH ; si vous pensez à une autre équipe, donnez-moi son nom ou son code.

**À savoir** : le report d'une fiche dont la période change en cours d'année ne reprend que la dernière période ; l'historique des périodes de l'année précédente reste dans la fiche de cette année.

**Vérifications** : tests automatiques (report de la période avec jours travaillés et fériés, refus d'un doublon, liste des années, équipes absentes de l'arbre) ; 70 tests passent ; essai navigateur sur instance jetable : 2026 → « + 2027 » → fiche 2027 créée avec 80 %, 4 jours, fériés travaillés, sélecteur 2026 / 2027 / + 2028.

## Version 0.13.1 — API Sedit RH : toutes les unités publiées

**Ce qui a changé** : j'ai modifié l'API Sedit RH elle-même (projet `C:\devpi-apps\sedit-rh`, fichier `backend/src/rh/rest.js`, route `/api/v1/organisation`). Elle publiait seulement l'organigramme SIIM (`SIIM_ORGANIGRAMME_V2`) ; elle y ajoute maintenant les **unités d'affectation portées par des agents en poste** (colonne `PST_AFFECT`) qui n'y figuraient pas, rattachées à leur service, avec le champ `origine: "agents"` et leur effectif. Pour la DSI : « Équipe projet éduc. innovation inclusion » (BF1112, 2 agents). Au total, 48 unités ajoutées dans l'API. Le schéma OpenAPI mentionne le nouveau champ ; la sauvegarde de l'ancien fichier est dans le répertoire temporaire de la session.

**À savoir**
- Cette modification est dans un autre projet que l'application : elle n'est **pas commitée** et la version déployée de l'API (autre serveur, Docker) doit être mise à jour pour que la liste soit complète en production.
- Les unités ajoutées viennent des affectations des agents : une unité sans aucun agent en poste ne peut pas être découverte ainsi (seul l'organigramme SIIM, ou une vue SQL plus complète côté Sedit RH, la donnerait).
- Pour redémarrer l'API de développement, il a fallu arrêter l'ancien processus et nettoyer un fichier de verrou périmé de sa base embarquée (`.dev-pg/postmaster.pid`) ; aucune donnée n'a été touchée.
- La liste d'unités de l'application a été actualisée depuis l'API.

**Vérifications** : l'API en développement renvoie BF1112 sous BF1 (« origine : agents ») ; 70 tests de l'application passent. Aucun test automatique n'existe dans le projet de l'API.

## Version 0.13.2 — Barre du haut adaptée aux fenêtres étroites

**Ce qui a changé** : hors plein écran, la barre du haut coupait « Tableau de bord RH », « Mon équipe »… sur deux lignes et débordait. Les libellés restent sur une ligne, les menus se resserrent, et sous 1250 px le menu passe sur sa propre ligne sous le titre.

**Vérifications** : essai dans un navigateur à 1150 px (menu sur sa ligne, aucun mot coupé). La partie droite de la barre (année, nom, boutons) n'a pas pu être vue à cette taille dans mon essai ; 70 tests passent.

## Version 0.14.0 — Unité de chaque agent, unités locales et responsable d'unité

**Ce qui a changé**
- **Mon équipe** : chaque carte a un bouton « ✎ Unité » : on choisit l'unité dans la liste des entités de la direction de la personne, et on coche « Responsable de cette unité » (la personne reçoit alors ★, et le responsable est enregistré dans l'unité).
- **Unités qui n'existent pas dans Sedit RH** : sous la liste, « L'unité n'existe pas ? La créer » ajoute une unité **locale** (par exemple « Numérique éducatif », dont Réda serait responsable, ou « Cellule administrative et financière » pour Isabelle) sous l'unité sélectionnée. Elle apparaît dans toutes les listes d'unités et n'est jamais supprimée par la synchronisation avec Sedit RH.
- **Année** : la liste déroulante du haut ouvre aussi la fiche de la même personne pour l'année choisie ; l'année n'est plus répétée dans l'en-tête de la fiche.

**À savoir**
- Une unité locale n'existe que dans cette application ; si Sedit RH la publie plus tard, il faudra rattacher les agents à la nouvelle unité.
- La création d'unités est ouverte aux valideurs dans leur périmètre : à restreindre aux administrateurs si vous préférez (Q20 du manifeste).
- Changer l'unité d'une personne ne change pas son valideur.

**Vérifications** : test automatique (création, doublon, liste de la direction, responsable, conservation par la synchronisation, refus pour un agent) ; 71 tests passent. Le dialogue et le sélecteur d'année n'ont pas été essayés à l'écran.

## Version 0.14.1 — Planning : raison pour mon équipe, présence pour les autres

**Ce qui a changé**
- **Simple agent** : ne voit que présence ou absence (jamais la raison), y compris sur sa propre ligne.
- **Encadrant** : voit la raison des congés des agents de son équipe et de sa propre fiche ; les autres fiches restent en présence / absence.
- **Disponibilité des encadrants** : un groupe « Encadrants — disponibilité » en tête du planning montre mes encadrants (ma chaîne de valideurs) et moi, en présence / absence ; auparavant, ni vos encadrants ni votre propre fiche n'apparaissaient s'ils n'étaient pas dans votre équipe.

**Vérifications** : test automatique (raison pour l'équipe et soi-même, présence seule pour le valideur, simple agent) ; 72 tests passent ; non essayé à l'écran.

## Version 0.14.2 — Planning : titres de groupe par entité

**Ce qui a changé** : dans le planning, Marc CHEVALIER apparaissait deux fois : dans « Encadrants — disponibilité » (sa ligne) et comme titre de groupe de son équipe. Les titres de groupe portent maintenant le nom de l'entité (par exemple « DIRECTION DES SYSTEMES D'INFORMATION »), comme dans Mon équipe ; la personne n'apparaît qu'en ligne.

**Vérifications** : syntaxe vérifiée, 72 tests passent ; non revu à l'écran.

## Version 0.14.3 — Mon équipe : les entités d'abord, puis leurs membres

**Ce qui a changé** : Mon équipe suivait la chaîne de validation. Il est maintenant classé par **entité** (unité) : un titre par unité, puis ses membres, **le responsable en premier (★)**, puis les valideurs, puis les agents. Exemple vérifié : « CELLULE ADMINISTRATIVE ET FINANCIÈRE » → Isabelle ABBAS ★, puis Florian BRUN. Une personne sans unité est rangée dans l'unité de son valideur ; les unités de même nom sont regroupées.

**Vérifications** : essai navigateur sur instance jetable (unité locale, responsable, deux groupes dans l'ordre attendu) ; 72 tests passent.


## Version 0.14.4 — Tableau de bord RH réservé aux administrateurs

**Ce qui a changé** : le Tableau de bord RH (taux d'absence, absences par direction et service, demandes en retard, RCH à échéance) n'était masqué que pour les agents ; les valideurs le voyaient aussi. Il est maintenant **réservé aux comptes administrateurs** : l'entrée de menu disparaît pour les autres, et l'ouvrir directement par son adresse (#/hr) ramène au tableau de bord habituel. Le contrôle est aussi fait côté serveur : un appel direct à l'API est refusé.

**Impact** : les valideurs qui consultaient ce tableau ne le voient plus ; ils gardent « Tableau de bord », « Mon équipe » et le planning de leur périmètre.

**Vérifications** : 73 tests passent, dont un nouveau (administrateur accepté, valideur et agent refusés) ; menu et redirection non essayés à l'écran.


## Version 0.15.0 — Utilisateurs : tableau compact et suppression multiple

**Ce qui a changé** : dans Paramétrage > Utilisateurs, les lignes sont moins hautes (la case « Admin » n'est plus sous le rôle : elle a sa propre colonne) et la colonne « Mot de passe » n'est plus affichée quand la connexion se fait par l'Active Directory. Une case à cocher par ligne (et « tout sélectionner » pour la page affichée) permet de **supprimer plusieurs utilisateurs d'un coup** : une confirmation liste les personnes, puis chaque compte est supprimé avec les mêmes règles qu'à l'unité (périmètre du valideur, jamais son propre compte) ; les refus éventuels sont affichés.

**Impact** : un compte administrateur ne peut plus changer le mot de passe local de secours d'un administrateur depuis ce tableau en mode AD (le mot de passe se fixe à la création).

**Vérifications** : 73 tests passent ; essai dans un navigateur sur une instance jetable (schéma temporaire, ensuite supprimé) : colonnes sans mot de passe en mode AD, case Admin en colonne, lignes compactes, sélection de deux comptes, confirmation listant les personnes puis suppression des deux ; l'affichage avec connexion locale (colonne « Mot de passe » conservée) n'a pas été essayé à l'écran.


## Version 0.16.0 — Mon équipe : valideur, unité entière, progression ; identifiants AD

**Ce qui a changé** : en créant une personne depuis Sedit RH, l'unité proposée est l'unité d'**affectation** de l'agent. Pour un directeur, Sedit RH l'affecte au secteur de sa direction (BF1 pour la Direction des systèmes d'information) alors qu'il dirige la direction entière (BF). Un agent dont le poste est « Directeur·trice … » (hors adjoint et direction générale) est maintenant proposé dans sa **direction**. La même règle s'applique à la liste des agents à rapprocher dans Mon équipe.

**Impact** : seules les nouvelles créations sont concernées ; les comptes déjà créés ne sont pas modifiés. L'unité reste modifiable dans le formulaire.

**Vérifications** : 5 tests automatiques (directeur, directrice, adjoint, direction générale, autre poste) ; non essayé à l'écran avec votre compte.

**Connexion par l'identifiant AD** : l'application cherchait l'identifiant saisi dans l'identifiant de l'application seul (« MCHEVALIER »), pas dans l'identifiant Active Directory (« machevalier ») : saisir son identifiant Windows échouait avec « Identifiant/mot de passe incorrect ». Les deux sont maintenant acceptés, sans tenir compte de la casse ; si un même identifiant AD est porté par deux comptes, la connexion est refusée. Le mot de passe est toujours vérifié par l'AD, inchangé. Vérifié par 2 tests automatiques.

**Identifiant = identifiant AD** : à la création d'une personne, l'identifiant du compte est maintenant celui de l'Active Directory quand il est trouvé (« machevalier » et non « MCHEVALIER »). Sans identifiant AD, l'ancienne règle (initiale du prénom + nom) s'applique ; en cas de doublon, un numéro est ajouté (casse ignorée). Les comptes déjà créés ne changent pas : leur identifiant se modifie dans Paramétrage > Utilisateurs.

**Mon équipe — valideur, unité entière, progression** : (1) chaque agent a un bouton « ↑ Valideur » pour le passer en valideur ; (2) le **responsable d'une unité en est automatiquement le valideur** : le désigner responsable passe un agent valideur et il valide les agents de son unité ; (3) dans « Agents Sedit RH à ajouter », une case par unité sélectionne **toute l'unité** d'un coup, puis on glisse la sélection sur une personne ; (4) un agent passé valideur (ou désigné responsable de son unité) **valide par défaut les agents de son unité** qui avaient le même valideur que lui (ex. Farouk pour le Bureau des projets) ; (5) **Ctrl + clic** sélectionne plusieurs personnes pour les glisser ensemble sous leur valideur ; (6) la création de plusieurs agents affiche une **barre de progression** (« Création 12 sur 31… ») au lieu de sembler figée.

**Impact** : les valideurs peuvent promouvoir un agent sans passer par un administrateur, dans leur périmètre. Les comptes déjà responsables d'unité mais restés agents ne sont pas modifiés automatiquement.

**Vérifications** : 83 tests automatiques dont 5 nouveaux (promotion, adoption de l'unité, responsable = valideur, identifiant AD) ; sélection multiple, barre de progression et case d'unité : vérifiés à l'écran sur une instance jetable (schéma temporaire, supprimé ensuite) : Ctrl + clic sur deux fiches puis glisser sur un valideur (« 2 personnes déplacées »), et « ↑ Valideur » sur un agent (badge Valideur, un collègue de l'unité rattaché sous lui). Non essayés à l'écran : la case par unité dans « Agents Sedit RH à ajouter » et la barre de progression de la création d'agents.

**Rattachement d'un agent Sedit RH** : en glissant un agent de « Agents Sedit RH à ajouter » sur son valideur, la fenêtre « Créer … » ne propose plus que les **entités de la direction de ce valideur** (par exemple celles de la Direction des systèmes d'information pour Marc CHEVALIER), au lieu de toutes les unités de la collectivité. Non essayé à l'écran.

**Valideur affiché, entités, retour en agent** : chaque carte de Mon équipe indique son **valideur** ; les noms d'entités ont un **fond plus pâle** et une entité créée localement porte la mention **« locale »** ; un bouton **« ↓ Agent »** repasse un valideur en agent (les personnes qu'il valide remontent sous son propre valideur, et il n'est plus responsable d'unité). Vérifié à l'écran (valideur sur les cartes, fonds, « locale », présence du bouton) et par un test automatique du retour en agent (84 tests passent) ; le clic sur « ↓ Agent » n'a pas été essayé à l'écran.

**Libellés de la période** : dans la fenêtre « Définir la période », le bouton s'appelle **« Créer la période »** ; une fois la période créée, la carte affiche **« Fiche congés »** au lieu de « Fiche 2026 » ; le bouton **« Reporter en 2027 »** propre à chaque carte est supprimé (le report se fait pour toute l'équipe avec « Reporter les périodes en 2027 »). Changement de libellés et retrait d'un bouton, non essayé à l'écran.

**Solde de CET** : la carte de chaque personne dans Mon équipe affiche son solde de CET (« CET : 60 j »). Dans la fiche, si le « Solde CET (j) » n'est pas saisi, **le solde de Sedit RH est utilisé comme solde initial** (affiché en grisé dans le champ) : la synthèse affiche alors initial − jours posés, comme le tableau de bord. Une valeur saisie n'est jamais remplacée. Le solde Sedit RH contient déjà les retraits que la DRH a enregistrés : un jour de CET à la fois enregistré dans Sedit RH et posé dans le calendrier serait compté deux fois. **À faire sur le serveur** : droit `cet:read` (et `absences:read`) sur la clé de l'application dans l'API Sedit RH, sinon l'affichage indique « indisponible » ou la synthèse garde 0.

**Valideur actuel et délégation** : l'en-tête de la fiche indique le « Valideur actuel » et, quand le valideur a délégué (absence ou période), le délégataire avec « par délégation de … ». **La délégation automatique est maintenant activée par défaut** pour tous les valideurs (migration 0009) ; chacun peut la désactiver dans « Délégation ».

**Absences de Sedit RH dans la fiche** : CM, GEM, CT, CP et SF saisis dans Sedit RH s'affichent en couleur claire dans le calendrier (jours ouvrés sans saisie), en lecture seule, sans la nature détaillée de l'arrêt. Les demi-journées de début et de fin ne sont pas distinguées : un jour est coloré en entier.

**Report des périodes et fin de contrat** : « Reporter les périodes en 2027 » s'arrête maintenant à la **date de fin de contrat** de Sedit RH (date de départ de l'agent) ; un contrat déjà terminé n'est pas reconduit. Une **fenêtre récapitulative** s'affiche ensuite : périodes reconduites (jusqu'à quelle date), limitées à la fin de contrat, non reconduites, refusées. Si Sedit RH est injoignable, la période couvre l'année entière et le récapitulatif le signale.

**Vérifications** : 94 tests passent ; vérification à l'écran : voir ci-dessous.

## Version 0.17.0 — Module exchange : absences dans l'agenda Outlook

**Ce qui a changé** : nouveau module **« exchange »**. Dans **Ma synthèse**, une carte « Agenda Outlook » propose de synchroniser automatiquement vos absences avec votre agenda. Pour chaque jour d'absence, votre agenda affiche un événement **« ABSENT »** (rien d'autre : ni motif, ni code), en disponibilité « Absent du bureau » ; une demi-journée donne un événement le matin (08:30-12:30) ou l'après-midi (13:30-17:30). Les jours de **télétravail** apparaissent en « **Travaille ailleurs** » (titre « Télétravail »). Les modifications de votre fiche passent dans l'agenda en moins de 10 minutes, ou tout de suite avec « Synchroniser maintenant » ; décocher la case retire les événements.

**À faire par l'administrateur avant usage** : créer une application dans Entra ID (Azure AD) avec le droit d'application **Calendars.ReadWrite** (consentement administrateur), puis renseigner `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID` et `GRAPH_CLIENT_SECRET` dans le `.env` (voir `.env.example`). Tant que ce n'est pas fait, la carte indique que le module n'est pas activé. Il faut aussi que les agents aient une adresse e-mail sur leur compte et une boîte Exchange Online. Conseil : limiter l'application aux boîtes concernées par une stratégie d'accès d'application Exchange.

**Choix à confirmer** : titre « Télétravail » pour les jours de télétravail (vous aviez demandé uniquement le mode « Travaille ailleurs ») ; horaires des demi-journées ; événements marqués « privés » ; les absences retenues sont celles du taux d'absence (y compris temps partiel TP et récupération d'heures RCH).

**Vérifications** : 105 tests automatiques (calcul des événements, journée, demi-journée, télétravail, création, mise à jour, suppression, panne, désactivation, jeton et nouvelles tentatives, routes) avec un Microsoft Graph **simulé**. **Non essayé avec un vrai agenda Outlook** : aucun identifiant Graph n'est disponible ici.

## Version 0.17.1 — Ma synthèse pour tous

**Ce qui a changé** : seuls les agents avaient « Ma synthèse ». Les **valideurs et les administrateurs** ont maintenant, eux aussi, l'entrée **« Ma synthèse »** dans le menu : leurs propres soldes (CA, RTT, CET…), leurs demandes récentes, leurs heures et la carte « Agenda Outlook ». Leur « Tableau de bord » reste celui de leur équipe. Si la personne n'a pas de fiche de congés pour l'année, la page l'indique.

**Vérifications** : test des routes inchangé (105 tests passent) ; vérification à l'écran : voir ci-dessous.

## Version 0.17.2 — Exchange passe par l'API Ville

**Ce qui a changé** : la synchronisation de l'agenda Outlook (module Exchange, 0.17.0) ne s'adresse plus à Microsoft Graph : elle passe par l'**API Ville** (`https://api.ivry.local`), avec la clé de l'application déjà présente dans le `.env` (`APM_API_URL` et `APM_API_KEY`). Les variables `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID` et `GRAPH_CLIENT_SECRET` ne servent plus et n'existent plus : plus d'application Entra ID à créer de notre côté.

**Point bloquant** : la documentation actuelle de l'API Ville (`/swagger.json`) propose la lecture des messages Office 365 mais **aucune route d'agenda**. Le module le détecte : la carte « Agenda Outlook » de Ma synthèse affiche « La synchronisation n'est pas encore disponible » avec la raison, et rien n'est envoyé. Elle fonctionnera dès que l'API Ville aura la route suivante (chemin réglable par `EXCHANGE_APM_EVENTS_PATH`) :

- `POST /api/v1/o365/calendar/events` avec `{mailbox, subject, start, end, isAllDay, showAs, isReminderOn, sensitivity}` (même forme qu'un événement Microsoft Graph, plus l'adresse de la boîte) ; réponse `{id}`.
- `DELETE /api/v1/o365/calendar/events/{id}?mailbox=<adresse>` ; réponse 204.
- Droit Microsoft côté APM : `Calendars.ReadWrite` (droit d'application), limité si possible aux boîtes des agents.

**Vérifications** : 106 tests automatiques (détection de la route, route absente, API Ville injoignable, clé jamais affichée, nouvelles tentatives, synchronisation complète avec une API Ville **simulée**). Vérifié sur l'API Ville réelle : la route d'agenda est absente, le module se déclare indisponible. **Jamais essayé avec un vrai agenda** : la route n'existe pas.

## Version 0.17.3 — Solde de CET en cache, agenda Outlook via l'API Ville

**Solde de CET en cache** : chaque solde lu dans Sedit RH est conservé en base (table `sedit_cet_cache`) et en mémoire. La page reçoit tout de suite la dernière valeur connue ; si elle a plus de 10 minutes, elle est **recalculée en arrière-plan**, sans faire attendre l'écran. Si Sedit RH est en panne, l'ancienne valeur reste affichée (l'infobulle donne sa date de lecture). Un agent qui n'a pas de CET est mémorisé aussi. Seul un solde jamais lu est demandé tout de suite à Sedit RH.

**CET « indisponible » sur le serveur Docker** : la carte indique désormais la raison. Les causes habituelles : (1) la clé de l'application dans l'administration de l'**API Sedit RH du serveur** n'a pas le droit `cet:read` (ni `absences:read`) ; (2) l'API Sedit RH du serveur n'a pas été reconstruite avec les routes `/cet` (`git pull && docker compose up -d --build` dans API-Nova) ; (3) `SEDITRH_API_URL` du `.env` Docker de Suivi des congés pointe vers `localhost` au lieu de l'adresse du serveur (`http://<serveur>:3440`) ; (4) `SEDITRH_API_KEY` est celle de votre poste local et non une clé créée sur le serveur.

**API Ville (APM) : routes d'agenda ajoutées** (projet `C:\dev\APM`, `backend/routes/proxy.js`) : `POST /api/v1/o365/calendar/events` et `DELETE /api/v1/o365/calendar/events/{id}?mailbox=…`, avec une nouvelle permission **« Agenda O365 (événements) »** (`o365_calendar`) à cocher sur l'application « Suivi des congés ». La boîte (`mailbox`) est obligatoire (on n'écrit jamais dans la boîte de collecte par défaut) et seuls les champs titre, horaires, disponibilité, confidentialité, rappel et catégories sont transmis à Microsoft. Elles utilisent l'application Microsoft déjà configurée dans l'APM ; **elle doit avoir le droit d'application `Calendars.ReadWrite`** (AppDSI ne lit que les agendas). 4 tests dans `backend/tests/o365-calendar.test.js` avec Microsoft simulé. **À faire** : déployer l'APM (reconstruire son image), puis cocher la permission sur l'application dans l'APM ; le module Exchange détecte la route et active la carte « Agenda Outlook ».

**Vérifications** : 110 tests pour Suivi des congés (cache en base simulée et réelle, recalcul en arrière-plan, panne de Sedit RH, redémarrage) et 4 pour l'APM ; **jamais essayé avec un vrai agenda Outlook ni sur l'APM déployée**.

## Version 0.17.4 — Report des périodes : seulement l'année suivante

**Ce qui a changé** : en affichant l'année 2027, Mon équipe proposait « Reporter les périodes en 2028 (12) ». Le bouton n'est plus proposé que pour **l'année qui suit l'année en cours** (2027 en 2026) et **uniquement pour les personnes qui n'ont pas encore cette fiche** ; quand une autre année est affichée, il disparaît. En janvier 2027, il proposera 2028.

**Vérifications** : syntaxe de l'interface contrôlée ; non essayé à l'écran (aucun test automatique : c'est de l'affichage).

## Version 0.17.5 — Jours demandés provisoires dans Outlook, CET contrôlé avec Sedit RH

**Agenda Outlook : jours demandés en provisoire** : quand vous demandez des jours (demande en attente de validation), ils apparaissent dans votre agenda en « ABSENT » avec la disponibilité **« Provisoire »**. Dès que le valideur accepte, l'événement passe en « Absent du bureau » ; s'il refuse, ou si vous annulez, il disparaît. (Le titre reste « ABSENT » : seul l'état « Provisoire » d'Outlook change.)

**Absences passées dans Outlook** : la synchronisation ne reprenait que les jours à partir d'aujourd'hui ; les absences d'octobre n'apparaissaient donc pas. Elle couvre maintenant du 1er janvier de l'année en cours à la fin de l'année suivante.

**Demande de CET refusée à tort** : avec un « Solde CET (j) » vide dans la fiche, la synthèse utilisait bien le solde de Sedit RH (60 jours) mais le contrôle de la demande partait de 0 et répondait « Solde insuffisant : il resterait -1,0 j ». Le contrôle utilise maintenant le même solde que la synthèse. Si Sedit RH n'est pas joignable et qu'aucun solde n'est connu, la demande est contrôlée avec 0 comme avant.

**Vérifications** : 115 tests passent (jour demandé provisoire puis validé puis refusé ; demande de CET avec et sans solde connu) ; Outlook non essayé en réel pour le provisoire.

## Version 0.17.6 — Agenda Outlook à jour à chaque demande, soldes prévisionnels

**Agenda Outlook** : plus besoin d'attendre la synchronisation périodique. Dès que vous (ou votre valideur) faites, validez, refusez ou annulez une demande, votre agenda est mis à jour en arrière-plan. Si vous supprimez un rendez-vous « ABSENT » dans Outlook, il est recréé à la synchronisation suivante. Cette détection demande la nouvelle version de l'API Ville (route de lecture des événements) : tant qu'elle n'est pas déployée, l'application continue comme avant.

**Soldes prévisionnels** : dans la synthèse, chaque solde (congés annuels, RTT, sujétion, bonification, CET, total) affiche en plus le « restant prévisionnel », c'est-à-dire ce qu'il resterait si vos demandes en attente étaient validées. La ligne n'apparaît que si vous avez des demandes en attente.

**Vérifications** : tests automatiques (mise à jour de l'agenda après une demande, recréation d'un événement supprimé, soldes prévisionnels). Non essayé en réel : la lecture des événements Outlook (API Ville à redéployer) et l'affichage dans le navigateur.

## Version 0.17.7 — Panneau de synthèse compact

**Synthèse de la fiche** : le panneau de droite était trop grand. Chaque solde tient maintenant sur une ligne (titre et restant) ; un clic sur le titre déplie le détail (droits, reliquat, pris, déduction…), et il reste déplié tant que vous ne le repliez pas. Le « restant prévisionnel » n'est affiché que s'il est différent du solde actuel, c'est-à-dire seulement quand des demandes sont en attente. À l'impression, tous les détails sont dépliés.

**Vérifications** : syntaxe du JavaScript et tests de version ; l'affichage n'a pas été contrôlé dans un navigateur (connexion non disponible dans l'instance d'essai).
