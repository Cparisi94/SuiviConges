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
