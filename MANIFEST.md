# MANIFEST — Suivi des congés : gestion des congés, RTT et heures des agents

> **Statut : v0.21.2 — manifeste « tel que construit » (as-built), établi le 2026-11-10 et mis à jour à chaque version.**
> Ce document décrit ce que l'application fait aujourd'hui, pourquoi, et selon quelles règles. Il est la référence
> fonctionnelle commune de la DRH, de la DSI et des développeurs. Il est **tenu à jour à chaque nouvelle version**
> (voir la section 29 et `CHANGELOG.md`).
> Chaque exigence porte un identifiant (`FIC-03`, `DEM-12`…) pour être référencée dans les tickets et les tests.
> Tout ce qui est **hypothèse** est marqué `[H]` ; tout ce qui attend une réponse est renvoyé vers la section 26 (`Q1`…).

Sources analysées pour ce document :

| Source | Apport |
|---|---|
| Code de l'application (`backend/`, `frontend/public/`) | comportement réel : règles, droits, écrans, API |
| `README.md` (version d'origine du prototype DRH) | description métier initiale, écarts avec le classeur Excel |
| `AMELIORATIONS-A-ETUDIER.md` (06/11/2026) | pistes d'évolution notées par le service métier |
| `GUIDE_NOUVELLE_APP_VILLE.md` | stack, PostgreSQL, API centrale APM, bonnes pratiques de la Ville |
| `modifications.md` | historique des évolutions techniques de la mise en conformité, expliquées pour le métier |
| Classeur « Modèle Suivi congés 2027.xlsx » (onglets Paramétrage et AGENT) | origine des règles de calcul (reproduites dans `rules.py`) |

---

## 0. Décisions validées

| # | Décision | Où |
|---|---|---|
| **D1** | L'application reste en **Python / Flask** (backend) et **JavaScript sans framework** (frontend) pour l'instant ; la réécriture en Node/Express + React/TypeScript du guide est reportée (option « migration progressive »). | 3, 24 |
| **D2** | Les données sont dans le **PostgreSQL de la Ville**, base `ivry_admin`, **schéma dédié `conges`**, avec migrations SQL numérotées. | 19 |
| **D3** | Les **dates restent stockées en texte** (« AAAA-MM-JJ HH:MM:SS ») pour ne pas toucher à la logique de calcul ; leur conversion en `TIMESTAMPTZ` est une étape ultérieure. | 19, 28 |
| **D4** | **Authentification des agents par l'Active Directory** via l'API centrale APM (`CONGES_AUTH_MODE=ad`) ; les comptes administrateurs gardent un mot de passe local de secours. | 15 |
| **D5** | Les **mails** (notifications, relances) partent par l'APM, pied de page paramétrable. | 16 |
| **D6** | **Ports** : backend **8110**, frontend interne **8111**, frontend DMZ **8112**. | 22 |
| **D7** | Un **frontend DMZ** distinct (même image, nginx restreint) est prévu ; l'API `/api/v1`, Swagger, `/api/status` et « se connecter en tant que » restent **internes**. | 22 |
| **D8** | Les administrateurs disposent de **« Se connecter en tant que »** (recherche prédictive dans l'AD), audité, comme dans l'application delib. | 14.4 |
| **D9** | Les données actuellement dans la base sont des **données de démonstration** (pas d'enjeu de reprise). | 26 |
| **D10** | **Versionnage** `0.x.y` (x = fonctionnalité, y = correctif, `1.0.0` = production), avec journal des versions et documentation à chaque livraison. | 29 |
| **D11** | **Aucun import/export Excel** n'est prévu par l'application en production (l'import de paramètres depuis le classeur reste un outil d'amorçage). | 14.3 |
| **D12** | Le **Paramétrage est un menu général à sous-sections** (calcul, utilisateurs, clés API, journaux, e-mails), comme dans l'application delib. | 14.1 |
| **D13** | Un **matricule** est porté par les comptes et les fiches (unique) ; il servira de clé de rapprochement avec **Sedit RH**. | 7.1, 14.2 |
| **D14** | Les **e-mails automatiques ont des gabarits modifiables** (objet, texte, variables) et une **mise en page commune** (expéditeur, signature, pied de page), dans l'application ; l'**activation de l'envoi** est un réglage de l'administrateur (pas du `.env`) ; l'en-tête est le gabarit institutionnel de l'APM. | 14.7 |
| **D15** | Deux **journaux d'administration** (connexions, e-mails) avec **durée de conservation réglable** ; les agents gérés par l'AD n'ont plus de gestion de mot de passe dans l'application. | 14.6, 15 |
| **D17** | Les **matricules des agents de la base** sont récupérés dans Sedit RH par rapprochement de **nom et prénom** (correspondances certaines seulement, validées par l'administrateur) ; 30 agents sur 34 rapprochés. | 14.9 |
| **D18** | L'**organisation Sedit RH** est présentée comme la hiérarchie de l'application (Direction › Service › Secteur › Agent) et permet de **créer des agents** dans l'application (comptes et fiches) en cochant des agents ou des unités ; les **comptes valideurs d'unité** manquants peuvent être créés (miroir de l'organisation RH). | 14.10 |
| **D19** | Les rôles se limitent à **Valideur et Agent** ; **Administrateur** est un **droit supplémentaire** (indicateur `admin`, case à cocher) qu'une personne agent ou valideur peut cumuler. Le niveau interne (direction, service, secteur, équipe…) reste porté par `users.role` et se déduit de l'**unité Sedit RH** de la personne ; un **agent** est affecté à une unité, un **valideur** à une unité et est validé par une **unité supérieure** (ses anciens rôles DGS/DGA/Direction/Service/Secteur/Unité/Équipe sont tous des « Valideur »). Le périmètre reste calculé par l'arbre des responsables, déduit des unités. | 14.11 |
| **D20** | Les **règles métier** sont consignées dans `backend/REGLES_METIER.md`, lisible dans Paramétrage > Documentation > Règles métier, et **mises à jour à chaque version** (règle ajoutée dans `CLAUDE.md`). | 14.12 |
| **D21** | Le menu **Mon équipe** montre l'arbre des personnes que je valide et permet, par **glisser-déposer** d'agents Sedit RH de mon niveau ou en dessous, de les créer **sous** une personne : celle-ci devient valideur (niveau déduit de son unité, plafonné sous celui de son propre valideur) et prend l'unité de l'agent déposé si elle n'en a pas. | 14.12 |
| **D22** | **Une personne n'a une fiche congés que si elle a au moins une période de paramètres** : le compte est créé d'abord, la fiche naît avec la première période (`POST /api/my-agents/<id>/fiche`). Les jours hors de toute période sont **grisés et refusés** (calendrier et demandes). | 14.12 |
| **D23** | Chaque période porte ses **jours travaillés** (1 = lundi … 7 = dimanche, du lundi au vendredi par défaut) et l'indicateur **jours fériés travaillés** ; les autres jours sont **grisés, non sélectionnables et non décomptés** (calendrier et demandes). Dans « Mes fiches », les groupes portent le **nom de l'entité** et le **responsable** passe en premier. | 14.12 |
| **D24** | Le **périmètre par défaut est l'équipe** (sous-arbre des personnes que l'on valide) **pour tous, administrateurs compris** ; l'administrateur peut basculer sur « **Voir tout** » (en-tête `X-Scope: all`, ignoré pour les autres profils). Les droits d'accès (ouvrir une fiche, administrer) ne changent pas. | 14.12 |
| **D25** | Les e-mails de demande portent des **boutons** : « Valider » / « Refuser » mènent à une **page de confirmation protégée par un jeton signé** (demande + destinataire, 14 jours) ; l'ouverture du lien n'a aucun effet, la décision est prise au clic (POST) avec les mêmes contrôles que l'écran ; « Voir le calendrier d'équipe » ouvre le planning de mon équipe. | 16, 14.13 |
| **D26** | Un valideur **délègue à son propre valideur** : automatiquement quand il est absent (journée complète posée dans sa fiche) et/ou sur des **périodes du/au** ; la délégation **prévient** le délégataire (mails, relances) et **trace** ses décisions ; elle ne crée pas de droit nouveau (un supérieur peut déjà valider). | 14.13 |
| **D27** | **« Mon équipe » remplace « Mes fiches »** : une seule vue, classée **par entité** (responsable ★ en premier, entités de même nom regroupées), où chaque personne est une carte avec sa **période en images** (camembert de quotité, jours travaillés, durée, pénibilité). La liste d'équipe, la création de fiche, la duplication N+1 et le glisser-déposer y sont réunis ; `#/agents` redirige vers `#/my-agents`. | 14.14 |
| **D16** | La connexion à **Sedit RH** (adresse et clé) est configurée dans `.env`, en local pour l'instant (API `api-apps/sedit-rh`, port 3440) ; un écran Paramétrage > API Sedit RH **teste la connexion et compte les agents**. | 14.8, 18 |

---

## 1. Vision et périmètre

### 1.1 Objectif
Permettre à la DRH de la Ville de **suivre, pour chaque agent et pour chaque année**, ses droits à congés (congés annuels,
RTT, jours de sujétion, bonifications, CET, reliquat), les **absences posées**, les **soldes restants**, et de faire
circuler les **demandes d'absence** dans la hiérarchie jusqu'à leur validation. L'application remplace un classeur Excel
(un onglet par agent) par une application web multi-utilisateurs qui **reproduit la logique de calcul du classeur**.

### 1.2 Ce que fait l'application
- une **fiche annuelle par agent** : paramètres (pénibilité, durée hebdomadaire, quotité, jours travaillés, dates d'arrivée et
  de départ, reliquat, solde CET) et **calendrier de saisie** (12 mois × 31 jours × 2 demi-journées) ;
- un **calcul en temps réel** des droits, des jours pris, des déductions et des soldes restants ;
- un **circuit de demandes** : absences en jours, absences en heures (CAH/RTTH), « cassage » d'un jour en 7 heures, déclaration
  d'heures de récupération (RCH), avec validation, refus, annulation et historique ;
- une **hiérarchie à 9 niveaux** (administrateur → DGS → DGA → direction → service → secteur → unité → équipe → agent) qui
  détermine qui voit, modifie et valide quoi ;
- des **tableaux de bord** (agent, valideur, RH) et un **planning mensuel** ;
- l'**administration** : comptes, rôles, paramétrage (codes, pénibilités, matrice de droits, jours fériés, vacances scolaires) ;
- une **API en lecture seule** pour les autres applications de la Ville, protégée par clés ;
- les **notifications** par mail aux valideurs et la **relance quotidienne** des demandes en attente.

### 1.3 Ce que l'application ne fait pas
- pas de **paie** ni de transmission à un logiciel de paie ;
- pas de **gestion des plannings de service** (horaires, astreintes, roulement) : seules les absences sont suivies ;
- pas de **délégation de validation** en cas d'absence du valideur (note métier, voir 28) ;
- pas d'**export Excel/CSV** ni d'**organigramme visuel** (notés au backlog) ;
- pas d'**application mobile** ni de mode hors ligne.

---

## 2. Origine : le classeur Excel et les écarts assumés

Les règles de calcul reproduisent les formules du classeur « Modèle Suivi congés 2027.xlsx » (fonctions `FLOOR`, `ROUND`,
`ROUNDDOWN`, `VLOOKUP`, `COUNTIF`, prorata, générations de sujétions, déductions). La **matrice de droits** (546 lignes × 6
colonnes, 3 276 valeurs) a été validée contre les valeurs en cache du classeur.

Écarts documentés par rapport au classeur (volontaires) :

| # | Écart |
|---|---|
| E1 | **CA26 dans le calendrier** : le classeur perd le code CA dans sa liste pour un reliquat de type « RP » (bug apparent). Ici, la liste proposée = liste du calendrier **+ CA n-1 si un reliquat reste à consommer**. |
| E2 | **Année dynamique** : le classeur fige 2027 dans plusieurs formules ; l'application utilise l'année de la fiche. Les dates sont bornées au 01/01–31/12 de cette année. |
| E3 | **Sujétions à intervalle nul** : si la durée de cycle calculée vaut 0, aucune sujétion n'est générée (le classeur affichait `#DIV/0!`). |
| E4 | **Reliquat** : borne étendue à 0–100 jours (classeur : 0,5–60). |
| E5 | **Durée hebdomadaire par défaut** : « 38 heures » à la création d'une fiche. |
| E6 | **Champs retirés** : « Sexe » et « Temps de travail » n'existaient pas sur la fiche du classeur. Le tableau « Durée → NB RTT » est une table interne du paramétrage. |

---

## 3. Contexte technique et conformité au guide de la Ville

| Sujet du guide | Situation (v0.1.0) |
|---|---|
| Backend Node.js + Express 5 | **Écart** : Python 3.12 + Flask (D1) |
| Frontend React 18 + TypeScript + Vite + Tailwind | **Écart** : HTML/CSS/JavaScript sans framework (D1) |
| PostgreSQL, schéma dédié, tables préfixées, requêtes paramétrées | **Conforme** : schéma `conges`, requêtes paramétrées, migrations SQL |
| Migrations versionnées | **Conforme** : `backend/migrations/0001_…` à `0003_…`, somme de contrôle |
| `.env`, aucune valeur en dur | **Conforme** : `backend/config.py`, `.env` / `.env.example` à la racine |
| Authentification AD via l'APM | **Conforme** (activée par `CONGES_AUTH_MODE=ad`) |
| Mail via l'APM, pied de page en paramètres | **Conforme** |
| API versionnée `/api/v1`, pagination, erreurs `{error}` | **Conforme** pour l'API publique ; les routes internes de l'écran ne sont pas versionnées |
| Swagger | **Conforme** : `/api-docs`, spécification `/api/v1/openapi.json` |
| `GET /api/status` | **Conforme** |
| Docker Compose backend + frontend, ports dédiés | **Conforme** (non encore exécuté sur un serveur Docker) |
| Reverse-proxy HTTPS | Prévu côté Ville ; nginx du frontend derrière |
| Données Ville (organisation, agents) via le Hub DSI | **Non utilisé** : la hiérarchie est saisie dans l'application `[H]` voir Q6 |
| Fichiers de plus de ~300 lignes à découper | **Écart** : `app.py` (≈ 3 500 lignes), `app.js` (≈ 4 300 lignes), `rules.py` (≈ 830 lignes) |
| Organisation `backend/` et `frontend/` | **Conforme** depuis la v0.1.0 |
| ESLint / TypeScript strict | **Non applicable** tant que le frontend est en JavaScript simple |
| Tests sur la logique critique | **Partiel** : 49 tests (voir 23) |

---

## 4. Glossaire et acteurs

### 4.1 Glossaire métier

| Terme | Sens dans l'application |
|---|---|
| **Fiche** | Dossier annuel d'un agent : paramètres + calendrier + demandes + soldes. Une fiche = un agent × une année. |
| **Matricule** | Numéro d'agent (clé de rapprochement avec Sedit RH), porté par le compte et la fiche. |
| **Année de la fiche** | Chaque fiche appartient à une année ; les écrans n'affichent que l'année sélectionnée. |
| **Propriétaire** | Compte valideur qui « possède » la fiche (détermine le périmètre de visibilité et de modification). |
| **Valideur (de la fiche)** | Compte qui valide les demandes de l'agent ; par défaut son responsable N+1 actif, sinon le propriétaire. |
| **Titulaire** | Le compte de l'agent lui-même (rôle « agent »), créé automatiquement avec sa fiche. |
| **Responsable d'unité** | Fiche marquée comme celle du responsable du compte propriétaire (une seule par propriétaire et par année) ; son nom est conservé dans l'historique des demandes. |
| **CA** | Congé annuel. **CA n-1 (CA26…)** : reliquat de l'année précédente, code dynamique selon l'année. |
| **Reliquat / report** | Jours de CA de l'année précédente restant à consommer. |
| **RTT** | Réduction du temps de travail (mensuelle), droit issu de la matrice selon la durée hebdomadaire. |
| **JS — Jour de sujétion** | Jours générés selon la pénibilité du poste, à des dates calculées. |
| **JB — Bonification** | Jours de bonification (formules AI5–AI9 du classeur). |
| **CET** | Compte épargne temps ; **dépôt CET** possible selon le solde. |
| **CAH / RTTH** | CA / RTT consommés **en heures** (créditent un compteur d'heures via le « cassage »). |
| **Cassage** | Transformation d'**un jour** de CA ou de RTT en **7 heures** utilisables en CAH/RTTH. Jamais sur le reliquat. |
| **RCH** | Récupération en heures : heures réalisées déclarées, **valables 6 mois**, consommées dans l'ordre d'ancienneté (FIFO). |
| **Pénibilité** | Modérée / Forte / Très forte : détermine les jours de sujétion. |
| **Quotité** | Taux d'activité (100 %, 90 %, 80 %…). |
| **Matrice de droits** | Table de 546 lignes (pénibilité × durée × quotité × jours hebdomadaires) donnant les droits annuels. |
| **Prorata** | Réduction des droits pour une arrivée ou un départ en cours d'année. |
| **Déduction** | Jours retirés des droits suite à certaines absences (maladie, grève, exclusion…). |
| **Périmètre** | Ensemble des comptes du sous-arbre d'un valideur : il voit et gère leurs fiches. |
| **Demi-journée** | Unité du calendrier : matin (0) ou après-midi (1). Clé = `mois×1000 + jour×10 + demi`. |
| **Vacances zone C / jours fériés** | Repères visuels du calendrier et du planning (paramétrables par année). |

### 4.2 Acteurs

| Acteur | Description |
|---|---|
| **Agent** | Consulte sa synthèse, saisit ses demandes d'absence, cassages, heures et récupérations. Ne modifie jamais directement son calendrier. |
| **Valideur** (équipe, unité, secteur, service, direction, DGA, DGS) | Gère les fiches de son périmètre, valide ou refuse les demandes, gère les comptes subordonnés. |
| **Administrateur** (DRH) | Voit et gère tout : fiches, utilisateurs, paramétrage, clés API ; peut agir « en tant que » un agent. |
| **Application tierce** | Consomme l'API `/api/v1` avec une clé (lecture seule). |
| **DSI** | Déploie, supervise (`/api/status`), gère la base, l'APM, la DMZ. |

---

## 5. Rôles, hiérarchie et périmètre

### 5.1 Niveaux (du plus élevé au plus bas)
`Administrateur (8) > DGS (7) > DGA (6) > Direction (5) > Service (4) > Secteur (3) > Unité (2) > Équipe (1) > Agent (0)`.
Les niveaux sont codés dans l'application (`ROLE_LEVELS`) ; les rendre configurables est au backlog.

### 5.2 Rattachement (qui peut être le responsable de qui)

| Rôle | Responsable autorisé |
|---|---|
| DGS | Administrateur |
| DGA | DGS |
| Direction | DGA, DGS ou Administrateur |
| Service | Direction |
| Secteur | Service ou Direction (un secteur peut être rattaché directement à une direction) |
| Unité | Secteur ou Service |
| Équipe | Unité ou Secteur |
| Agent | tout valideur (obligatoire) |
| Administrateur | aucun |

- **HIE-01** — Un utilisateur ne peut pas être son propre responsable ; un administrateur n'a pas de responsable ; un agent doit être rattaché.
- **HIE-02** — Un niveau peut être **sauté** (ex. un secteur directement sous une direction).
- **HIE-03** — À la suppression d'un compte, ses subordonnés **remontent** au premier ancêtre dont le rôle reste valide.
- **HIE-04** — Création de comptes : un valideur ne peut créer que des rôles **strictement inférieurs** au sien et placés dans son périmètre ;
  l'administrateur peut créer tous les rôles.

### 5.3 Matrice des droits

| Action | Agent | Valideur (dans son périmètre) | Administrateur |
|---|:-:|:-:|:-:|
| Voir une fiche | la sienne | celles du périmètre | toutes |
| Créer une fiche | non | oui | oui |
| Modifier paramètres / propriétaire / valideur d'une fiche | non | oui (périmètre) | oui |
| Saisir directement des absences dans le calendrier | **non** (même la sienne) | oui (jamais sur sa propre fiche d'agent) | oui |
| Demander une absence en jours | pour sa fiche | non (il saisit directement) | oui |
| Demander cassage / heures / récupération | pour sa fiche | oui (périmètre) | oui |
| Valider / refuser une demande | non | si assigné, **ou supérieur hiérarchique** du valideur assigné (jamais un subordonné) | toutes |
| Annuler une demande en attente | la sienne | oui | oui |
| Demander l'annulation d'une demande validée | oui | oui | oui |
| Approuver / refuser une annulation | non | comme la validation | oui |
| Créer / modifier des comptes | non | périmètre : paramètres, mot de passe ; ni rôle, ni rattachement, ni identifiant | tout |
| Paramétrage, clés API, « en tant que » | non | non | oui |
| Tableau de bord RH | non | **non** | oui |

- **DRO-01** — Tous les contrôles sont faits **côté serveur** ; l'interface masque seulement ce qui n'est pas permis.
- **DRO-02** — Les **tableaux de bord, listes de fiches et planning** sont automatiquement limités au périmètre du compte.
- **DRO-03** — Les agents voient le planning de leur équipe, mais le **motif des absences des collègues est masqué** (code générique « A »).

---

## 6. Périmètre fonctionnel — vue d'ensemble

| Module | Section | Description |
|---|---|---|
| Fiche agent | 7 | paramètres, périodes, propriétaire, valideur, multi-année, duplication, impression |
| Calendrier et codes | 8 | grille de saisie, sélection de plage, codes colorés, week-ends, fériés, vacances |
| Moteur de calcul | 9 | droits, prorata, sujétions, bonifications, reliquat, déductions, CET, soldes |
| Demandes et validation | 10 | absences, cassage, heures, récupération ; circuit, annulation, historique |
| Heures | 11 | compteurs CAH / RTTH, RCH (6 mois, FIFO), cassage |
| Tableaux de bord | 12 | agent, valideur, RH |
| Planning mensuel | 13 | vue par mois, regroupement hiérarchique, impression |
| Administration | 14 | utilisateurs, audit des comptes, paramétrage, clés API, « en tant que » |
| Authentification | 15 | local / AD, secours, limitation des essais |
| Notifications | 16 | mail au valideur, relance quotidienne |
| API externe | 17 | `/api/v1`, clés, Swagger, état |
| Intégrations | 18 | APM (AD, mail), PostgreSQL, Hub DSI (non utilisé) |

---

## 7. Fiche agent

### 7.1 Contenu
- **FIC-01** — Identité : nom et prénom (en majuscules), e-mail (obligatoire, valide), **matricule** (facultatif, unique — voir ADM-05).
- **FIC-02** — Rattachement : **propriétaire** (un valideur actif), **valideur** de la fiche, année, indicateur « responsable d'unité ».
- **FIC-03** — Paramètres de calcul : **pénibilité**, **durée hebdomadaire** (35 h … 38 h), **quotité** (100 % … 50 %), **jours travaillés par semaine**
  (5 … 1), **date d'arrivée**, **date de départ**, **reliquat** (jours), **solde CET**.
- **FIC-04** — **Périodes multiples** : une fiche peut comporter plusieurs périodes de paramètres dans l'année (changement de quotité, de durée…) ;
  les droits sont calculés par période puis cumulés.
- **FIC-05** — À la création d'une fiche, un **compte agent** est créé automatiquement (identifiant = **identifiant Active Directory** quand il est connu, ex. « machevalier » ; à défaut initiale du prénom + nom en majuscules ;
  suffixe numérique en cas de doublon, casse ignorée), rattaché au propriétaire. En mode AD, l'« Identifiant AD » du compte doit correspondre à l'identifiant Ville (voir Q3).
- **FIC-06** — Un seul « responsable d'unité » par propriétaire et par année : en désigner un nouveau retire l'ancien.

### 7.2 Multi-année
- **MUL-01** — Un **sélecteur d'année** est dans la barre supérieure ; l'année proposée par défaut est un paramètre (Paramétrage > Année par défaut).
- **MUL-02** — Jours fériés et vacances scolaires sont paramétrables **par année** (2026 et 2027 sont préchargés).
- **MUL-03** — **Duplication vers l'année suivante** : depuis la liste (une fiche, une sélection, toutes). Les paramètres sont conservés **sauf les dates
  d'arrivée et de départ** ; les congés saisis ne sont **pas** copiés. **Clonage** d'une fiche dans la même année également possible.

### 7.3 Liste des fiches et impression
- **FIC-07** — La liste regroupe les fiches par **niveau hiérarchique** du compte propriétaire (couleurs de brique identiques au planning) ; un secteur rattaché
  directement à une direction apparaît sous celle-ci.
- **FIC-08** — **Impression** d'une fiche en **une seule page A4 paysage** (paramètres masqués, synthèse compactée sur trois colonnes) ; les couleurs sont conservées.
- **FIC-09** — Changement de propriétaire d'une fiche (modale dédiée) selon le périmètre ; suppression d'une fiche par son responsable.

---

## 8. Calendrier et codes d'absence

- **CAL-01** — Grille **12 mois × 31 jours × 2 demi-journées**. Un clic ou un **glisser sur plusieurs demi-journées** sélectionne une plage ; le code choisi s'applique à toute la sélection.
- **CAL-02** — Repères visuels : **week-ends**, **jours fériés**, **vacances scolaires zone C** (liseré orange), couleurs des codes identiques à celles du classeur.
- **CAL-03** — La saisie directe est réservée aux **valideurs et à l'administrateur** (jamais au titulaire) ; l'agent passe par une **demande** (section 10).
- **CAL-04** — Les dates sont **bornées à l'année de la fiche** ; une demi-journée ne porte qu'un seul code.
- **CAL-05** — Les **absences en heures** (CAH, RTTH, RCH) s'affichent sous forme de notes d'heures sur les jours concernés ; elles **occupent** les demi-journées correspondantes
  (aucune absence en jours ne peut être posée au même endroit).

### 8.1 Codes d'absence (paramétrage actuel — modifiables par l'administrateur)

| Code | Libellé | Code | Libellé |
|---|---|---|---|
| CA | Congé annuel | CA26 (n-1) | Report CA année N-1 |
| RTT | RTT mensuelle | RTTH | RTT en heures |
| CAH | Congé annuel en heures | RCH | Récupération en heures |
| JS | Jour de sujétion | JB | Bonification |
| CET | Compte épargne temps | MD | Médaille |
| CM | Congé maladie | CP | Congé parental |
| CT | Congé maternité / adoption / paternité | GEM | Garde d'enfant malade |
| SF | Soins à entourage familial | AS | ASA / événement familial |
| AI | Absence injustifiée | ET | Exclusion temporaire |
| GR | Grève | SX | Absence syndicale |
| TP | Temps partiel | FP | Formation professionnelle |
| TT | Télétravail | | |

- **COD-01** — **Codes demandables par l'agent** (ordre métier) : CA, CA n-1 (seulement s'il reste du reliquat), RTT, JB, JS, MD, AS, CET.
- **COD-02** — **Codes comptés dans le taux d'absence RH** : AI, AS, CA, CA n-1, CAH, CET, CM, CP, CT, ET, GEM, GR, JB, JS, MD, RTT, RTTH, SF, SX, TP, RCH.
  **TT (télétravail) n'est pas une absence** ; RC a été retiré.

---

## 9. Moteur de calcul (`rules.py`)

Le moteur est **pur** (sans accès base) et reproduit les formules du classeur. Il est appelé en temps réel à chaque modification de la fiche
(`POST /api/compute`) et par les tableaux de bord.

- **CAL-10** — **Droits annuels** : lus dans la **matrice** (pénibilité × durée × quotité × jours hebdomadaires) — CA, RTT, jours de sujétion (JS), jours de bonification (JB), droit CET.
- **CAL-11** — **Prorata** d'arrivée / de départ : droits réduits au nombre de jours calendaires de présence dans la période.
- **CAL-12** — **Sujétions** : générées à des dates calculées selon un intervalle de cycle ; si l'intervalle est nul, aucune sujétion n'est générée (écart E3).
- **CAL-13** — **Bonifications** : formules AI5 / AI6 / AI7 / AI9 du classeur.
- **CAL-14** — **Reliquat** : intégré au solde dès la saisie (droit), qu'il soit consommé ou non ; consommé via le code CA n-1.
- **CAL-15** — **Déductions** : certaines absences (maladie, grève, exclusion…) **réduisent les droits** (RTT, JS…) selon les formules AO30 / AO31.
- **CAL-16** — **Soldes restants** : droit − pris, par type (CA, RTT, JS, JB, CET, CAH, RTTH, RCH) et **total** ; « généré à ce jour » pour les droits qui s'acquièrent au fil de l'année.
- **CAL-17** — **Dépôt CET possible** calculé selon les droits restants.
- **CAL-18** — **Ce qui peut être cassé en heures** : CA de l'année uniquement (jamais le reliquat) et RTT déjà générés à ce jour.
- **CAL-19** — **Périodes multiples** : calcul par période (`compute_multi`) puis cumul.
- **CAL-20** — Arrondis, planchers et recherches reproduisent les fonctions `ROUND`, `FLOOR`, `ROUNDDOWN`, `VLOOKUP`, `COUNTIF`, `DATEDIF` d'Excel.

---

## 10. Demandes et circuit de validation

### 10.1 Types de demandes

| Type | Qui demande | Contrôles principaux |
|---|---|---|
| **absence** (jours) | le titulaire (ou l'administrateur) | code autorisé, demi-journées valides dans l'année, pas de chevauchement avec une absence, une demande en attente ou des heures, **solde suffisant**, reliquat CA n-1 disponible |
| **cassage** | titulaire ou responsable | code CA ou RTT, **une journée entière**, droits suffisants ; crée 7 h d'heures valables 6 mois |
| **heures** (CAH / RTTH) | titulaire ou responsable | date dans l'année, horaires cohérents, durée = écart horaire, **pas de chevauchement**, solde d'heures suffisant |
| **recuperation** (RCH) | titulaire ou responsable | date de réalisation dans l'année, nombre d'heures > 0 ; valable 6 mois |

- **DEM-01** — Une **pièce jointe** facultative (PDF, images, Word, Excel, ODT/ODS, texte ; **5 Mo maximum**) peut accompagner une demande d'absence.
- **DEM-02** — **Validateur** d'une demande = validateur de la fiche, à défaut le **responsable N+1 actif** du demandeur, en remontant la hiérarchie, à défaut un administrateur.
- **DEM-03** — **Validation automatique** : sans valideur au-dessus (cas d'un administrateur), ou lorsqu'un **responsable** saisit lui-même une demande de cassage / d'heures / de récupération pour un agent de son périmètre.
- **DEM-04** — À la création, le **nom du compte valideur** et celui du **responsable d'unité** sont **figés** dans la demande (historique fidèle même si l'organisation change).

### 10.2 États et transitions

```
                     ┌──────────── refus ───────────▶ refusee
 soumission ─▶ en_attente ──── validation ─────────▶ validee ──▶ annulation_demandee ─┬─ approbation ─▶ annulee
                     │                                                                  └─ refus ───────▶ validee
                     └── annulation (par le demandeur / titulaire / admin) ─▶ annulee
 (validation automatique : soumission ─▶ validee directement)
```

- **DEM-10** — **Valider** : seulement si la demande est « en attente » ; le valideur doit être l'assigné **ou l'un de ses supérieurs hiérarchiques** (jamais un subordonné) ; la validation **revérifie** les contrôles
  (solde, chevauchement) et écrit les cases du calendrier / les heures ; en cas de conflit survenu entre-temps → erreur 409.
- **DEM-11** — **Refuser** (avec commentaire de décision).
- **DEM-12** — **Annuler** une demande **en attente** : par son auteur, le titulaire ou l'administrateur.
- **DEM-13** — **Demander l'annulation** d'une demande **validée** (avec motif) : elle passe en « annulation demandée » ; le valideur l'**approuve** (les cases / heures sont supprimées) ou la **refuse** (la demande redevient validée).
- **DEM-14** — On ne peut **pas annuler** une demande dont **des heures ont déjà été consommées** (cassage / récupération).
- **DEM-15** — Chaque étape est tracée dans l'**historique des événements** de la demande (soumise, auto-validée, validée, refusée, annulation demandée, annulation validée…) avec l'acteur et le commentaire.
- **DEM-16** — Écran **Demandes** : liste filtrable (statut, code, recherche), **badge** du nombre de demandes à traiter dans le menu, accès à la pièce jointe pour les personnes habilitées.

---

## 11. Heures : CAH, RTTH, RCH

- **HEU-01** — **Une journée = 7 heures** (cassage : 1 jour → 7 h ; heures : durée / 7 = fraction de jour).
- **HEU-02** — Les **compteurs d'heures** (CAH, RTTH) sont crédités par les **cassages validés** ; les cassages **en attente réservent le jour** sans créditer d'heures.
- **HEU-03** — **RCH** : heures réalisées, **valables 6 mois** à partir de la date de réalisation ; consommées **dans l'ordre d'ancienneté** (FIFO) ; les heures expirées ne sont plus utilisables.
- **HEU-04** — Le **détail des heures** est consultable (modale) : crédits, consommations, expirations, par code.
- **HEU-05** — Un valideur peut **modifier ou supprimer** des heures déjà posées sur sa fiche (jamais l'agent).
- **HEU-06** — Alerte : les **RCH qui expirent dans les 30 jours** sont signalées (tableau de bord RH, rappels).

---

## 12. Tableaux de bord

- **TDB-01** — **Synthèse de l'agent** (« Ma synthèse ») : ses soldes et l'accès à sa fiche (message d'invitation si aucune fiche n'existe pour l'année).
- **TDB-02** — **Tableau de bord du valideur** : une ligne par fiche du périmètre (case « toutes les fiches ») avec cycle, CA pris / restant, RTT, sujétions, bonification, CET, total pris / restant ;
  regroupement par responsable.
- **TDB-03** — **Tableau de bord RH** (comptes administrateurs uniquement : menu masqué, accès direct et API refusés aux autres) : **taux d'absence** = jours d'absence ÷ capacité de travail, global, **par direction / service** et en **arbre hiérarchique** ;
  **demandes en retard** (en attente depuis plus de 3 jours) ; **RCH proches de l'expiration**. Les heures d'absence sont converties en jours (7 h = 1 jour).
- **TDB-04** — Si le calcul d'une fiche échoue (fiche incomplète), la ligne affiche l'erreur **sans casser** le tableau.

---

## 13. Planning mensuel

- **PLA-01** — Vue d'un **mois** : les absences de chaque agent jour par jour, avec **week-ends, jours fériés et vacances scolaires** ; **totaux par agent**.
- **PLA-02** — Portée : « mes fiches » ou « **toutes les fiches de mon périmètre** » regroupées par niveau hiérarchique (dégradés de brique du plus sombre — direction — au plus clair — secteur).
- **PLA-03** — Les agents voient leur équipe avec les **motifs masqués** (DRO-03).
- **PLA-07** — `GET /api/planning` : la **raison** (code) n'est donnée qu'à un encadrant, pour les fiches de son équipe et la sienne (`masked` faux) ; toute autre fiche, et tout planning d'un simple agent, n'affichent que **présence / absence** (code « A »). Les fiches des **encadrants** (ma chaîne de valideurs, et la mienne) sont ajoutées (`supervisor`), groupe « Encadrants — disponibilité ».
- **PLA-05** — Les jours d'une **demande en attente** apparaissent dans le planning **éclaircis et en pointillé**, comme dans la fiche ; les jours validés gardent la couleur pleine du code.
- **PLA-04** — **Impression** du planning en A4 paysage, sans la synthèse mensuelle.

---

## 14. Administration : le menu Paramétrage

### 14.1 Menu général
- **ADM-00** — **Paramétrage** (administrateur) est un **menu à sous-sections** (barre latérale, regroupées par thème) :
  **Congés** — Calcul et calendrier ; **Accès** — Utilisateurs, Clés API, Journal des connexions ;
  **E-mails** — Expéditeur et pied de page, Messages automatiques, Journal des e-mails ; **Intégrations** — API Sedit RH, Organisation RH, Matricules.
- Les anciennes adresses `#/users` et `#/apikeys` redirigent vers le Paramétrage pour un administrateur. Les **valideurs non administrateurs** gardent l'entrée « Utilisateurs » du menu principal (limitée à leur périmètre).

### 14.2 Utilisateurs
- **ADM-01** — Création, modification, désactivation, suppression de comptes (voir 5) ; l'administrateur peut modifier l'identifiant, le rôle, le rattachement ; un valideur gère les paramètres des comptes de son périmètre.
- **ADM-02** — Champ **« Identifiant AD »** : identifiant Ville utilisé pour la connexion AD lorsqu'il diffère de l'identifiant de l'application.
- **ADM-05** — Champ **« Matricule »** (lettres, chiffres, `.` `_` `-`, 20 caractères au maximum) : **unique** parmi les comptes ; refusé s'il est déjà attribué (message nommant le compte). Il est aussi porté par la **fiche** (saisi à la création, modifiable) et recopié sur le compte de l'agent.
- **ADM-03** — **Journal d'audit des comptes** : création, changement d'identifiant, de rôle, de responsable, d'activation, de **matricule**, de mot de passe (jamais la valeur), suppression, usurpation (début / fin), avec l'acteur réel.
- **ADM-04** — Garde-fous : on ne peut pas retirer ses propres droits administrateur ni désactiver son propre compte ; recherche, filtres (rôle, actif) et pagination dans la liste.
- **ADM-06** — En **mode AD**, la colonne « Mot de passe » n'est proposée que pour les administrateurs (compte de secours) et la création d'un compte **n'exige pas de mot de passe** (sauf pour un administrateur).

### 14.3 Calcul et calendrier (paramétrage métier)
- **PAR-01** — Codes d'absence (libellé, couleur, présence dans la grille), pénibilités, durées hebdomadaires, quotités, jours hebdomadaires, table « durée → RTT », **matrice de droits**, jours fériés, vacances scolaires, **année par défaut**.
- **PAR-02** — Le paramétrage est stocké en base (table `settings`) ; un **réimport depuis le classeur Excel** (copié dans `source/`) existe comme outil d'amorçage (D11).

### 14.4 Clés API
- **ADM-10** — Écran **Clés API** (administrateur) : création (nom, périmètres, IP autorisées, expiration), désactivation, suppression, **journal des appels** (voir 17).

### 14.5 « Se connecter en tant que »
- **ACT-01** — Réservé aux **administrateurs**. Bouton « En tant que… » : **recherche prédictive** (≥ 2 lettres) dans l'**AD** via l'APM, complétée par les comptes de l'application (utilisables si l'AD est indisponible).
- **ACT-02** — L'administrateur **agit avec exactement les droits de l'agent**, sans connaître son mot de passe ; un **bandeau** rappelle l'usurpation avec « Revenir à mon compte ».
- **ACT-03** — **Interdits** : un autre administrateur, un compte désactivé, soi-même, un agent sans compte dans l'application (grisé avec le motif), l'enchaînement de deux usurpations, le changement de mot de passe du compte usurpé.
- **ACT-04** — **Traçabilité** : début et fin journalisés (journal d'audit des comptes **et** journal des connexions) ; les modifications de comptes et les décisions sur les demandes faites pendant l'usurpation sont attribuées à l'**administrateur réel** avec la mention « en tant que ».

### 14.6 Journal des connexions
- **LOG-01** — Chaque **connexion réussie**, **échec** (identifiant inconnu, mot de passe incorrect, compte désactivé, service AD indisponible, trop de tentatives), **déconnexion** et **début / fin de « en tant que »** est inscrit : date et heure, événement, identifiant saisi, résultat et motif, **méthode** (local, Active Directory, secours), **adresse IP** et navigateur.
- **LOG-02** — Écran **Journal des connexions** (administrateur) : recherche (identifiant ou adresse IP), filtres (événement, succès / échec, période), pagination par 50, lignes d'échec mises en évidence.
- **LOG-03** — **Conservation** : durée réglable (30 à 3 650 jours, 365 par défaut) ; les entrées plus anciennes sont **supprimées automatiquement** (au démarrage et toutes les 6 heures). L'écriture du journal ne fait **jamais** échouer une connexion.
- **LOG-04** — L'adresse IP enregistrée est celle vue par l'application : elle dépend de `CONGES_PROXY_HOPS` derrière un reverse-proxy (voir 22).

### 14.7 E-mails : activation, expéditeur et pied de page, messages automatiques, journal
- **MAI-00** — **Activation de l'envoi** : une case à cocher (« Envoi automatique des e-mails ») dans Paramétrage > E-mails ; **désactivé par défaut** ; ce n'est plus une option du `.env`. Désactivé, les e-mails automatiques ne partent pas (ils sont inscrits au journal, statut « non envoyé »).
- **MAI-08** — Les **messages de test partent toujours**, même si l'envoi automatique ou le message est désactivé, dès que l'API centrale (APM) est configurée.
- **MAI-01** — **Expéditeur et pied de page** (écran « Expéditeur et pied de page »), communs à tous les e-mails : **nom** et **adresse de l'expéditeur** (vides = valeurs par défaut de l'APM), **signature** (ajoutée au texte), **pied de page** (trois lignes et couleur). Envoi d'un message de test. **Pas de prévisualisation** de l'en-tête ni du pied de page : ils sont ajoutés par l'API centrale.
- **MAI-09** — L'**en-tête** des e-mails est le **gabarit institutionnel de l'APM** : l'API centrale n'accepte que l'expéditeur et le pied de page en paramètres ; il n'est donc pas paramétrable depuis l'application (voir Q15).
- **MAI-02** — **Messages automatiques** : écran en deux parties — **liste des messages à gauche**, **contenu à droite** (objet, texte, activation) ; adresse `#/settings/messages/<message>`. Messages actuels : **Nouvelle demande à valider** (au valideur), **Relance des demandes en attente** (au valideur, une fois par jour) et **Message de test**. Le registre est extensible (un nouveau message = une entrée dans `mail_templates.py`).
- **MAI-03** — **Variables** : `{agent}`, `{code}`, `{dates}`, `{lien_fiche}`… ; la **liste des variables du message avec leur signification** est affichée à côté du texte et chaque variable s'insère d'un clic. Une **variable inconnue est refusée** à l'enregistrement ; une **ligne dont toutes les variables sont vides est supprimée**.
- **MAI-04** — Le texte est du **texte brut** : tout est échappé à l'envoi (pas d'HTML saisi), les adresses `http(s)` deviennent des liens. **Aperçu du message seul** (données d'exemple), **envoi de test** à une adresse saisie à côté du bouton (mémorisée dans le navigateur ; l'e-mail du compte n'est pas requis), **retour au texte d'origine** par message.
- **MAI-05** — Les e-mails partent par l'APM : le pied de page et l'expéditeur sont transmis **en paramètres** (`footer1..3`, `footerColor`, `from_name`, `from_email`), la signature fait partie du contenu. Les réglages sont stockés dans la table `settings` (clé `mail`, y compris `enabled`) ; à défaut, le pied de page vient de `CONGES_MAIL_FOOTER*`.
- **MAI-06** — **Journal des e-mails** (administrateur) : pour chaque envoi ou tentative, date, destinataire, objet, **message** concerné, **statut** (envoyé, échec avec l'erreur, non envoyé — envoi désactivé, message désactivé, APM non configurée, pas d'adresse), texte envoyé (bouton « Voir »), demande concernée. Recherche, filtres (statut, message, période), pagination, **conservation réglable** comme le journal des connexions.
- **MAI-07** — L'écran signale l'état de l'envoi (activé, désactivé, APM non configurée).

### 14.8 API Sedit RH : test de connexion
- **SED-01** — Écran **Paramétrage > Intégrations > API Sedit RH** (administrateur) : affiche l'**adresse** configurée et si la **clé** est renseignée (la clé n'est **jamais** affichée ni renvoyée) ; adresse et clé se règlent dans `.env` (`SEDITRH_API_URL`, `SEDITRH_API_KEY`).
- **SED-02** — Le bouton **« Tester la connexion et compter les agents »** interroge l'API Sedit RH et affiche : le **résultat** (connexion réussie ou en échec), le **temps de réponse**, le **nombre d'agents en poste** et leur **répartition par statut** (avec barres de proportion).
- **SED-03** — Le nombre d'agents est lu dans les **effectifs agrégés** (`GET /api/v1/effectifs?par=statut`, droit `effectifs:read`) : **aucune donnée personnelle** d'agent n'est lue ni enregistrée. La clé doit donc porter les droits `effectifs:read` (en plus de `agents:read` et `organisation:read`).
- **SED-04** — En cas d'échec, la **cause** est expliquée : API non configurée, injoignable (réseau), clé refusée (401 : invalide, expirée ou suspendue), accès refusé (403 : droit manquant, avec le détail renvoyé par l'API), autre erreur du serveur.

### 14.9 Matricules : rapprochement avec Sedit RH
- **RH-01** — Écran **Paramétrage > Intégrations > Matricules** : pour chaque agent de l'application **sans matricule**, recherche dans les agents **en poste** de Sedit RH par **nom et prénom** (comparaison sans accents ni ponctuation).
- **RH-02** — Résultats : **certaine** (un seul agent de ce nom — proposée et pré-cochée), **ambiguë** (homonymes : jamais appliquée, candidats affichés), **introuvable** (à saisir à la main dans Utilisateurs), **déjà attribuée** (le matricule appartient à un autre compte). L'administrateur **décoche** ce qu'il ne veut pas appliquer.
- **RH-03** — Application : le matricule est écrit sur le **compte** et sur **toutes les fiches** de l'agent ; **jamais d'écrasement** d'un matricule déjà renseigné ; unicité respectée ; chaque application est inscrite au journal d'audit des comptes (« Rapprochement avec Sedit RH »).
- **RH-04** — Résultat sur la base actuelle : 30 agents sur 34 rapprochés, 4 introuvables.

### 14.10 Organisation RH et création d'agents
- **ORG-01** — Écran **Paramétrage > Intégrations > Organisation RH** : arborescence **Direction › Service › Secteur › Agent** construite depuis Sedit RH (agents en poste), à l'image de la hiérarchie de l'application ; un niveau identique au niveau supérieur (même code ou même libellé) est **fusionné**.
- **ORG-02** — Chaque unité affiche son **nombre d'agents**, le nombre d'agents **absents de l'application** et le **compte valideur** de l'application qui porte le même nom (ou « pas de compte valideur ») ; chaque agent indique s'il est **déjà dans l'application** (par matricule ou par nom).
- **ORG-03** — **Recherche** (nom, prénom, matricule), filtre (tous / absents / déjà présents), **actualisation** à la demande ; dépliage à la demande (2 400 agents).
- **ORG-04** — **Sélection** : case par agent (seuls les agents absents sont cochables) ou case d'**unité** (secteur, service, direction) qui coche tous ses agents absents ; compteur de sélection.
- **ORG-05** — **Création** (« Créer les agents sélectionnés ») avec options : **année** des fiches, **créer les comptes valideurs manquants** (direction, service, secteur — sous le compte du même nom s'il existe, sinon sous l'administrateur ; identifiants `DIR-…`, `SRV-…`, `SEC-…`, mot de passe aléatoire inconnu), **propriétaire par défaut**, **recherche dans l'AD**. Un **aperçu** (agents à créer, déjà présents, ignorés, comptes d'unité à créer, e-mail trouvé) précède toujours la création ; la création est **tout ou rien** et **idempotente** (un agent déjà présent est ignoré).
- **ORG-06** — Chaque agent est créé avec son **compte** (rôle agent) et sa **fiche**, rattachés au compte de son unité le plus bas (secteur, sinon service, sinon direction) ou au propriétaire par défaut ; le **matricule** vient de Sedit RH ; la **date d'arrivée / de départ** n'est reprise que si elle tombe dans l'année de la fiche (prorata correct) ; les autres paramètres de calcul (pénibilité, durée, quotité) restent à renseigner (non fournis par Sedit RH).
- **ORG-07** — **E-mail et identifiant AD** : cherchés dans l'annuaire (APM) par nom ; retenus **seulement si un seul compte correspond** ; sinon l'agent est créé **sans e-mail** (à renseigner dans sa fiche) et sans identifiant AD (à renseigner dans Utilisateurs pour qu'il puisse se connecter).
- **ORG-08** — Les **comptes d'unité** créés sont des comptes valideurs **structurels**, à attribuer à leurs responsables (en leur donnant un identifiant AD) ; ils sont journalisés (« Création depuis l'organisation Sedit RH »).
- **ORG-09** — **Protection des données** : la liste des agents RH n'est lue qu'à la demande de l'administrateur, gardée **5 minutes en mémoire** et **jamais écrite** sur disque ni en base ; seuls les agents créés ou rapprochés sont enregistrés. Toutes ces routes sont réservées aux administrateurs.

---

### 14.11 Trois rôles, unités Sedit RH et création d'une personne
- **ADM-07** — Deux rôles à l'écran, **Valideur** et **Agent**, plus la case **Administrateur** (droit cumulable, réservé aux administrateurs, avec mot de passe local de secours) ; l'API des utilisateurs expose `profil` (valideur/agent) et `admin` en plus de `role` (niveau interne) ; un compte `admin` a tous les droits quel que soit son rôle ; la valeur `valideur` envoyée en modification conserve le niveau interne du compte (sinon « secteur »).
- **ADM-08** — Table **`org_units`** (code, libellé, niveau, parent) copiée depuis `/api/v1/organisation` de Sedit RH à la première utilisation puis sur demande (`GET /api/org-units?refresh=1`, administrateur) ; colonnes `users.unit_code` et `users.validator_unit_code` (migration `0005`). Un valideur ne voit que les unités de son périmètre (son unité et ses descendantes).
- **ADM-09** — **Création d'une personne** (`POST /api/users/person`) : recherche prédictive dans Sedit RH (`GET /api/sirh/agents?q=`, mots multiples), rapprochement avec l'AD (`GET /api/ad/match`, identifiant attendu = initiale du prénom + nom, ex. `cparisi`) pour l'e-mail et l'identifiant, puis unité(s).
- **ADM-10** — **Agent** : unité d'affectation obligatoire ; rattaché au valideur de cette unité, à défaut au valideur de l'unité supérieure la plus proche (les comptes d'unité hérités sont reconnus par leur niveau et leur nom) ; compte et fiche créés. Refus explicite si aucune unité de la chaîne n'a de valideur.
- **ADM-11** — **Valideur** : unité d'affectation + **unité qui le valide**, obligatoirement une unité supérieure (pas de cycle possible) ; rattaché au valideur de cette unité ; sans unité validatrice, il est rattaché à celui qui le crée (ou à personne si c'est un administrateur). Le niveau interne est celui de son unité. **Direction** : aucune unité supérieure dans Sedit RH, le valideur est un **DGA** (ou DGS) choisi dans la liste des valideurs de ces niveaux ; un DGA/DGS se crée avec le champ « niveau de validation » (sans unité, `level` et `supervisor_id` dans l'API) ; le valideur supérieur doit toujours être d'un niveau plus élevé.
- **ADM-12** — Un valideur ne peut créer que dans son périmètre (unité et valideur de rattachement) ; seul un administrateur crée un administrateur. Toute création est inscrite au journal d'audit (profil, niveau, unités, matricule).
- Question ouverte **Q17** : faut-il migrer les comptes d'unité hérités (« DIR-… », « SRV-… ») vers des personnes titulaires, et renseigner leur unité (aujourd'hui rapprochés par nom) ?


### 14.12 Mon équipe et règles métier
- **MAG-01** — Menu **Mon équipe** (valideurs et administrateurs) : arbre `GET /api/my-agents` des personnes que je valide, puis de celles que mes subordonnés valident, avec effectifs.
- **MAG-02** — Liste de droite `GET /api/my-agents/sirh?q=` : agents en poste de Sedit RH dont l'unité est la mienne ou en dessous (toutes pour un administrateur sans unité), absents de l'application (par matricule ou nom), hors moi-même ; 300 résultats au plus, recherche par nom, prénom, matricule ou unité.
- **MAG-03** — Dépôt d'un agent Sedit RH sur une personne (`POST /api/my-agents/attach`) : crée compte et fiche (propriétaire et valideur = cette personne), unité confirmée dans mon périmètre, e-mail et identifiant AD repris s'ils sont uniques ; la personne devient valideur (`users.role` = niveau de son unité, sous celui de son propre valideur) et prend l'unité de l'agent si elle n'en avait pas.
- **MAG-04** — Déplacement (`POST /api/my-agents/move`) : change le valideur et le propriétaire de la fiche ; refusé sous soi-même ou un subordonné, hors périmètre, pour un compte administrateur sans valideur, ou si le valideur de destination n'est pas d'un niveau plus élevé.
- **MAG-06** — **Sélection multiple** : cases à cocher (et « Tout sélectionner ») dans la liste Sedit RH ; glisser un agent coché emmène toute la sélection (un agent non coché part seul) ; le dépôt crée les agents un par un via `POST /api/my-agents/attach`, chacun dans son unité Sedit RH ou dans une unité commune ; le bilan distingue créés et échecs.
- **MAG-07** — **Fiche = première période** : l'attache d'un agent et la création d'une personne ne créent plus de fiche ; l'arbre montre « Définir la période » (ou « Compléter la période » si une fiche existante est vide) puis le lien de la fiche de l'année ; la période est validée contre les listes du paramétrage (pénibilité, durée liée à la pénibilité, quotité, jours/sem.) ; sa date de début est la date d'arrivée Sedit RH si elle tombe dans l'année, sinon le 1er janvier, sa fin le 31 décembre.
- **MAG-08** — **Hors de mon unité** : `GET /api/my-agents/sirh?scope=all` liste les agents de toute la collectivité ; le rattachement d'un agent d'une autre unité est permis, toujours sous une personne de mon périmètre ; la liste des unités du dialogue est complète (`GET /api/org-units?scope=all`).
- **CAL-06** — Les **jours couverts par aucune période de paramètres** (ou, sans période, hors de la présence arrivée → départ) sont **grisés et non sélectionnables** dans le calendrier ; le serveur refuse une demande d'absence sur ces jours.
- **CAL-07** — **Jours travaillés** : `jours_travailles` (liste 1–7, effectif = `jours_hebdo`) et `ferie_travaille` dans chaque période (et dans `params` quand il n'y a qu'une période implicite) ; un jour est sélectionnable s'il est couvert par une période, que son jour de semaine est coché et qu'il n'est pas férié (sauf fériés travaillés). Contrôle identique côté serveur (`_cell_covered`).
- **FIC-10** — « Mes fiches » : le groupe d'un responsable porte le **nom de son entité** (`users.unit_code` → libellé Sedit RH), la fiche du responsable passe **en premier** (surlignée) dans le groupe de l'entité qu'il valide.
- **TDB-05** — Arbre du tableau de bord RH : libellé d'un nœud = **nom de l'entité** (`users.unit_code` → `org_units.libelle`), à défaut le nom du compte ; la fiche du **responsable** passe en premier dans l'entité qu'il valide (« (Responsable) ») ; les entités de même nom sont fusionnées ; `_org_ancestor_name` (tableau par direction / service) suit la même règle.
- **FIC-14** — En-tête de fiche compact (une ligne de champs `fb-grid`) ; en mode **Mes congés** (`#/agent/<id>/conges`) la fiche est en **consultation** : champs désactivés, ni suppression ni changement de valideur, le calendrier ne sert qu'à poser des demandes (l'API ne retire pas pour autant au valideur ou à l'administrateur ses droits sur une fiche, voir DRO-01).
- **FIC-13** — Barre d'onglets des fiches : le bouton **« + »** ouvre une **liste de choix** des fiches de l'année dans mon périmètre (recherche, cases à cocher, fiches déjà ouvertes grisées) et ouvre les fiches cochées en onglets ; il ne crée plus de fiche (la création se fait dans « Mes fiches » ou « Mon équipe »).
- **FIC-12** — Vocabulaire : le « propriétaire » d'une fiche s'appelle **« Valideur »** à l'écran, désigné par **Prénom NOM** (`nom_famille`, `prenom`) et jamais par son identifiant ; les listes de choix du valideur (`owner_options`, `/api/validators`) portent un champ `display`.
- **FIC-11** — Nom de famille et prénom mémorisés séparément sur le compte (`nom_famille`, `prenom`) ; à défaut, repris de Sedit RH par matricule.
- **CGE-02** — `GET /api/my-leave?year=` renvoie l'identifiant de ma fiche (titulaire = moi), indépendamment de mon périmètre : un valideur retrouve ainsi sa propre fiche, qui appartient à son valideur.
- **CGE-03** — Sur **sa propre fiche** (titulaire), personne ne saisit ni ne valide directement, **administrateur compris** : `can_edit_cells` est faux, `can_request` vrai ; les demandes de jours, d'heures et de cassage suivent le circuit normal (valideur = responsable N+1, à défaut un autre administrateur, à défaut validation d'office) ; DEM-03 ne s'applique pas à sa propre fiche.
- **CGE-01** — Menu **Mes congés** (route `#/my-leave`, tous les profils) : ouvre la fiche de l'année dont la personne est le titulaire (`agent_user_id`), en mode « congés » (`#/agent/<id>/conges`) où le bloc **Paramètres et périodes** est masqué ; sans fiche, message explicatif. Pour un agent, le menu « Mes fiches » est masqué.
- **MAG-09** — Rapprochement AD : à nom égal, le compte qui a une adresse e-mail est préféré ; la pastille « ⚠ e-mail » de Mon équipe signale les personnes actives sans e-mail (une demande dont le valideur n'a pas d'e-mail est journalisée « non envoyé » dans le journal des e-mails).
- **DRO-04** — `_scope_ids` renvoie le sous-arbre de l'utilisateur ; seul un administrateur qui envoie `X-Scope: all` obtient tous les comptes. S'appliquent : fiches, planning, demandes (« à valider », « périmètre »), compteurs, rappels, arbre Mon équipe (racine « Toute la collectivité »). L'écran Utilisateurs de l'administration reste complet.
- **MAG-10** — **Recherche AD** : `GET /api/my-agents/<id>/ad[?q=]` (rapprochement par nom, ou texte libre) et `POST /api/my-agents/<id>/ad {username}` : reprend l'e-mail (relu dans l'annuaire) et l'identifiant AD sur le compte et ses fiches ; refus si l'identifiant est déjà utilisé ; tracé au journal d'audit.
- **MAG-12** — Bouton **« Dupliquer pour N+1 »** sur chaque personne de Mon équipe qui a une fiche (`fiche.next_exists` indique si la fiche N+1 existe) : appelle `POST /api/agents/duplicate` (MUL-03 : paramètres conservés sauf arrivée / départ, congés non copiés).
- **MAG-05** — Les unités proposées dans le dialogue sont limitées à mon périmètre (`GET /api/org-units?scope=mine`).
- **DOC-01** — `GET /api/docs/regles-metier` sert `backend/REGLES_METIER.md` à tout utilisateur connecté ; l'écran Paramétrage > Documentation > Règles métier l'affiche. Toute règle métier ajoutée ou modifiée y est inscrite dans la même version.
- Question ouverte **Q18** : un agent glissé sous une personne dont l'unité diffère de la sienne (unité non supérieure) est accepté — faut-il l'interdire ?

### 14.13 Délégation, e-mails à boutons, Mon équipe en deux niveaux
- **DEL-01** — Table `delegations` (valideur, du, au) et `users.delegate_auto` (migration `0007`) ; le **délégataire est le responsable direct** (`parent_id`) ; menu **Délégation** (`/api/delegation`).
- **DEL-02** — Délégation active un jour donné : période explicite le couvrant, **ou** délégation automatique et valideur **absent ce jour-là** (deux demi-journées posées dans sa fiche).
- **DEL-03** — Pendant une délégation, le mail de **nouvelle demande** est aussi envoyé au délégataire (jeton à son nom) et la **relance quotidienne** lui est adressée.
- **DEL-04** — « Validations faites à ma place » : décisions (validée / refusée) prises par une autre personne que moi sur les demandes qui me sont attribuées, avec l'auteur, les dates, le code et le commentaire (100 dernières).
- **DEL-05** — Garde-fous : le délégataire doit exister et être actif ; une période passée ou inversée est refusée.
- **NOT-05** — E-mail de demande : variable `dates` en **plages** (`format_ranges`, week-ends sautés), boutons `[[bouton:Texte|URL]]` (variables `lien_valider`, `lien_refuser`, `lien_calendrier`) rendus en boutons HTML, repliés en « Texte : URL » dans le texte et le journal ; les lignes sans adresse (CONGES_BASE_URL vide) disparaissent. Un texte par défaut ancien jamais personnalisé est remplacé par le nouveau.
- **NOT-06** — `GET /api/mail-action/<jeton>` affiche la demande et deux boutons sans rien enregistrer ; `POST` enregistre la décision comme l'écran (`approve` / `refuse`, droits et soldes revérifiés) ; jeton signé (`itsdangerous`, sel `mail-action`) valable 14 jours ; le lien est **personnel**. `CONGES_BASE_URL` doit pointer vers le frontal public (qui relaie `/api`).
- **MAG-11** — `GET /api/my-agents?depth=` : par défaut **les personnes que je valide directement** et, pour mes délégants du moment, les leurs ; `depth=all` (bouton « Voir toute ma ligne hiérarchique ») : tous les niveaux ; `count` = tous les subordonnés.
- **PLA-06** — Lien `#/planning?equipe=1&mois=M&annee=A` : planning de mon équipe, au mois et à l'année demandés.

### 14.14 Mon équipe par entité (fusion avec Mes fiches)
- **EQP-01** — Vue **par entité** : un groupe par **unité** (Sedit RH ou locale ; à défaut l'unité du valideur ; « Sans unité »), classé par chemin hiérarchique ; dans un groupe : le **responsable d'unité** (★, `org_units.head_user_id`), puis les valideurs, puis les agents ; unités de même nom regroupées ; un titre accepte les dépôts (= sous le responsable de l'entité).
- **EQP-02** — Carte : nom, rôle (Valideur / Agent, Admin), pastilles (délégation, effectif sous sa responsabilité, ⚠ e-mail), **période en cours** (`fiche.period` : quotité en camembert, jours travaillés L M M J V S D, durée, pénibilité, fériés « F », nombre de périodes), actions (fiche, Définir / Compléter la période, Dupliquer pour N+1, Recherche AD).
- **EQP-03** — En-tête : **+ Nouvelle fiche** et **Dupliquer toutes les fiches pour N+1** (celles sans fiche N+1) ; glisser-déposer d'une carte sur une carte ou sur l'en-tête d'une entité (= sous le responsable de cette entité).
- **EQP-05** — Fiche : e-mail et matricule **verrouillés** (champs désactivés ; `PUT /api/agents/<id>` conserve la valeur existante) ; case « Resp. unité » retirée de l'écran (`is_manager` reste en base pour l'existant) ; champ **Unité** : `GET/PUT /api/my-agents/<id>/unit` proposent **toutes les unités de la direction** de la personne (à défaut, celles de mon périmètre) ; Mon équipe en deux colonnes (équipe large, Sedit RH 330 px).
- **ANN-01** — Fiche : **sélecteur d'année** (`GET /api/my-agents/<id>/years`) pour passer d'une année à l'autre de la même personne ; option « + N+1 (reporter la période) ».
- **ANN-02** — **Report de période** (`POST /api/agents/duplicate`) : crée la fiche N+1 avec une **période explicite** reprenant la dernière période de l'année (paramètres, `jours_travailles`, `ferie_travaille`) sur toute l'année ; congés, arrivée et départ non copiés ; refus si la fiche existe déjà. Remplace l'ancienne duplication qui perdait les jours travaillés.
- **UNI-03** — **Unités locales** (`org_units.local = 1`, codes `LOC001`…, migration `0008`) créées par `POST /api/my-agents/units` (nom + unité parente dans mon périmètre, niveau déduit du parent, doublon refusé) ; jamais supprimées par la synchronisation Sedit RH. **Responsable d'unité** : `org_units.head_user_id` (un compte ne dirige qu'une unité), posé par `PUT /api/my-agents/<id>/unit {unit_code, head}` ; ★ sur la carte (`unit_head`). Bouton « ✎ Unité » de Mon équipe. Le sélecteur d'année du haut ouvre la fiche de la même personne pour l'année choisie ; l'année n'est plus affichée dans l'en-tête de la fiche.
- **UNI-02** — **À la source** : l'API Sedit RH (`api-apps/sedit-rh/backend/src/rh/rest.js`, route `/organisation`) complète l'organigramme SIIM par les unités `PST_AFFECT` des agents en poste (rattachées à leur service, `origine: agents`, effectifs inclus) ; 48 unités ajoutées ; schéma OpenAPI `Secteur.origine`. UNI-01 reste en secours côté application.
- **UNI-01** — `sedit_rh.organisation_units` complète `/api/v1/organisation` par les **équipes portées par des agents** (codes `service` / `secteur` / `affectation` absents de l'arbre), niveau « équipe », rattachées par préfixe de code (ex. BF1112 → BF1).
- **EQP-04** — Le menu « Mes fiches » est retiré ; l'ancien écran n'est plus joignable.

## 15. Authentification et sessions

- **AUT-01** — **Mode local** (`CONGES_AUTH_MODE=local`) : mots de passe de l'application (hachage scrypt, 8 caractères minimum, changement par l'utilisateur).
- **AUT-02** — **Mode AD** (`ad`) : le mot de passe est vérifié par l'AD via l'APM (`POST /api/v1/ad/authenticate`) avec l'« Identifiant AD » ou l'identifiant ; le compte doit **exister dans l'application** (rôle, rattachement).
- **AUT-03** — **Compte de secours** : en mode AD, les **administrateurs** acceptent aussi leur mot de passe local ; les autres reçoivent « service d'authentification indisponible » (503) si l'APM est en panne.
- **AUT-04** — Le changement de mot de passe dans l'application est **refusé** aux comptes gérés par l'AD, et le **bouton « Mot de passe » n'est pas affiché** à ces agents (en mode AD, seuls les administrateurs conservent un mot de passe local de secours).
- **AUT-05** — **Session** : cookie signé (`HttpOnly`, `SameSite=Lax`, `Secure` en HTTPS), valable 10 h ; l'identité n'est jamais lue dans un en-tête fourni par le client.
- **AUT-06** — **Limitation des essais** : 8 échecs en 15 minutes par adresse (+ 10 par minute côté nginx) ; message d'erreur identique pour un compte inconnu et un mot de passe faux.
- **AUT-09** — L'**identifiant de connexion est insensible à la casse** (si deux comptes ne diffèrent que par la casse, seule la saisie exacte est acceptée).
- **AUT-07** — **Premier démarrage** : un compte `admin` est créé avec `CONGES_INITIAL_ADMIN_PASSWORD` ou un mot de passe aléatoire affiché une fois.
- **AUT-08** — Chaque tentative de connexion est **journalisée** (voir 14.6) avec la méthode utilisée ; à la création d'une fiche en mode AD, l'écran indique que l'agent se connecte avec son compte Ville (sans afficher de mot de passe).

---

## 16. Notifications

- **NOT-01** — Chaque **nouvelle demande** envoie un **mail au valideur** : agent, code, demi-journées, nombre de jours, commentaire, liens vers la fiche et vers les demandes à valider (`CONGES_BASE_URL`).
- **NOT-02** — **Relance quotidienne** : un mail par valideur listant ses demandes en attente depuis **plus de 3 jours**, au plus une fois par jour.
- **NOT-03** — Les mails passent par l'APM (corps HTML échappé) ; le **contenu** de chaque message, l'**expéditeur**, la **signature** et le **pied de page** se règlent dans Paramétrage > E-mails (14.7) ; **un échec d'envoi n'empêche jamais** l'enregistrement d'une demande ; l'envoi est désactivé tant que l'administrateur ne l'active pas. Chaque envoi est inscrit au journal des e-mails.
- **NOT-04** — Non couvert : mail à l'agent lors de la validation / du refus, alerte RCH à 30 jours par mail (backlog).

---

## 17. API externe, clés et supervision

- **API-01** — **API `/api/v1` en lecture seule** : `GET /agents`, `GET /agents/{id}`, `GET /agents/{id}/balance`, `GET /absences`, `GET /requests`. Listes **paginées** (`limit`, `offset`), erreurs `{ "error": … }`.
- **API-02** — **Clés** `cgk_` + 64 caractères hexadécimaux, en-tête `X-API-Key` (ou `Authorization: Bearer`), **affichées une seule fois**, stockées hachées (SHA-256).
- **API-03** — **Périmètres** : `agents:read`, `balances:read`, `absences:read`, `requests:read`, `managers:read` (ou `*`) ; **IP/réseaux autorisés** et **expiration** facultatifs ; désactivation immédiate.
- **API-12** — **Manager d'un agent** : `GET /api/v1/managers?q=…` (droit `managers:read`) cherche parmi les comptes actifs (sauf administrateurs purs ; `inclure_inactifs=1` pour les autres) par **matricule** ou **e-mail** exact, ou par **mots du nom RH** (Sedit RH : `nom`, `nom_famille`, `prenom` ; accents et casse ignorés, début de mot suffisant) ; le nom AD n'est ni cherché ni renvoyé. Chaque résultat porte l'identité RH de l'agent, son unité, son **manager** (le valideur du compte, `users.parent_id`) et `delegue_actuel` (délégataire du manager ce jour-là, sinon `null`). Pagination `limit`/`offset` (20 par défaut, 100 au plus) ; `q` : 2 caractères au moins.
- **NOM-01** — **Nom AD affiché par défaut** : `users.nom_ad` (migration `0012_nom_ad.sql`) reçoit le `displayName` de l'AD (par l'APM `ad/search`, correspondance exacte sur l'identifiant AD) à la création d'un compte et, pour les comptes existants, en arrière-plan à l'affichage de Mon équipe (`people.fill_ad_names_async`, un passage à la fois, pause de 10 min ; un compte inconnu de l'AD n'est pas réinterrogé avant redémarrage) ou à la demande (`POST /api/users/ad-names/sync`, administrateur). Mon équipe, l'en-tête et le valideur de chaque carte affichent le nom AD ; le **nom RH** apparaît en dessous, petit et en italique, seulement s'il diffère (mêmes mots dans un autre ordre = identique).
- **NOM-02** — **Nom d'affichage unique** : `db.user_label(row)` (et son équivalent SQL `USER_LABEL_SQL`) donne le nom de toute personne affichée dans l'application, au format **« Prénom NOM »** : le nom AD (`users.nom_ad`) s'il existe, sinon prénom + nom de famille, sinon le nom enregistré, sinon l'identifiant. `db.ad_display` remet le `displayName` de l'AD (« NOM Prénom ») dans cet ordre (« GAULTIER Djamel » → « Djamel GAULTIER ») ; `people.normalize_ad_names` convertit les noms déjà enregistrés (au démarrage). Il remplace les formats mélangés des cartes, du tableau de bord, des fiches, des demandes et des recherches ; le nom RH reste affiché en dessous, petit et en italique, quand il diffère (NOM-01) ; l'API `/api/v1/managers` ne renvoie que le nom RH.
- **ACT-01** — **Activation d'un compte sans AD** (`backend/activation.py`, migration `0014_activation.sql`, table `activations`, colonnes `users.mobile` et `users.mobile_verifie_le`) : `POST /api/users/<id>/activation` (administrateur, ou valideur de la personne dans son périmètre ; personne active, sans identifiant AD, avec matricule) génère un code « XXXXX-XXXXX » (50 bits, valable 7 jours, usage unique, seul son haché est conservé, un nouveau code annule le précédent) et un QR code (`segno`, optionnel) d'un lien `CONGES_MOBILE_URL/#activation=MATRICULE.CODE` (le fragment n'est pas envoyé au serveur). Côté agent, quatre appels sans session (`POST /api/activation/start|sms|otp|password`, relayés par `conges-mobile-dmz`) : matricule + code ; numéro de smartphone (06/07, normalisé) -> SMS à 6 chiffres envoyé par l'APM (`apm.send_sms`, `POST /api/v1/sms/send`, droit `sms_send` sur la clé) ; code SMS -> numéro enregistré ; mot de passe (10 caractères, lettres et chiffres, sans identifiant, matricule ni numéro). **Durcissement** : message unique « Informations incorrectes ou code expiré » (matricule inconnu ou code faux), 5 codes erronés = activation verrouillée, SMS : 3 envois, 60 s entre deux, 10 minutes, 5 essais, numéro déjà vérifié sur un autre compte refusé, limites 10/15 min par adresse et 6/15 min par matricule, nginx 12 requêtes/min, chaque étape dans le journal des connexions (événement `activation`), e-mail de prévenance si l'agent a une adresse. Connexion : un compte activé (`mobile_verifie_le`) s'authentifie par mot de passe local, par identifiant **ou matricule**, même en mode AD ; son mot de passe se change dans l'application (non géré par l'AD). Le même parcours sert de réinitialisation.
- **ACT-02** — **E-mail facultatif et mot de passe oublié** : `POST /api/activation/email` (étape facultative entre le SMS et le mot de passe : adresse valide et unique, enregistrée dans `users.email` et la fiche) ; `POST /api/activation/forgot` et `/reset` : compte actif, non administrateur, smartphone contrôlé ; code SMS à 6 chiffres haché (10 minutes, 5 essais, 3 envois par heure, 4 demandes / 15 min par identifiant, 6 par adresse) ; réponse identique que le compte existe ou non ; mot de passe enregistré, jetons « se souvenir de moi » supprimés, journal, prévenance par e-mail ou SMS.
- **ACT-03** — **Confirmations par SMS pour les personnes sans e-mail** (`backend/sms_notify.py`, appelé par `_audit_request`) : à chaque événement d'une demande d'absence (soumise, validée, refusée, annulée, annulation demandée / acceptée / refusée), un SMS est envoyé par l'APM aux personnes **sans adresse e-mail et dont le smartphone est contrôlé** (agent, valideur qui reçoit la demande, valideur qui décide) ; envoi en arrière-plan, jamais bloquant, tracé dans `mail_logs` (modèle `sms`, numéro masqué).
- **ACT-04** — **« Se souvenir de moi » et verrou biométrique** : migration `0015_remember.sql` (table `remember_tokens`, haché seul) ; `POST /api/auth/login` accepte `remember` (30 jours, cookie `conges_remember` HttpOnly, 5 appareils, refusé aux administrateurs) ; `current_user` rétablit la session par ce jeton ; déconnexion et changement de mot de passe le révoquent. Version mobile : case à la connexion et verrou local WebAuthn (authentificateur de la plateforme, vérification de l'utilisateur obligatoire, non vérifié par le serveur). Documentation : `docs/ACCES_AGENTS_SANS_AD.md`, diagrammes BPMN `docs/bpmn/`.
- **MOB-01** — **Version mobile (frontend dédié, DMZ uniquement)** : dossier `conges-mobile-dmz/` (page HTML/CSS/JS sans build, nginx, Docker, `dev_server.py` pour un poste sans Docker), projet séparé de `frontend/` sur le modèle de `elus-dmz` de delib ; le nginx ne relaie que `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/me`, `GET /api/mobile/summary|days`, `POST /api/requests` et `POST /api/mobile/requests/<id>/cancel|cancel-request` (annulation d'une demande en attente ; demande d'annulation d'une demande validée, à accepter par le valideur ; réservées à MES demandes) ainsi que, pour l'agenda du téléphone, `GET /api/mobile/calendar`, `POST /api/mobile/calendar/link|revoke` et le flux `GET /cal/<jeton>.ics` relayé vers `/api/ical/<jeton>.ics` (douze routes en tout ; tout le reste : 404 ; `X-Scope` effacé ; 5 connexions par minute et par adresse). Backend : `backend/mobile.py` — `GET /api/mobile/summary?year=` (ma fiche seulement : compteurs, demandes en cours, agenda, codes demandables, périodes couvertes et fériés) et `GET /api/mobile/days?du=&au=&debut=&fin=` (demi-journées posables : jours travaillés de la fiche, hors fériés, hors cases occupées ; 120 jours au plus, une seule année). La demande est créée par `POST /api/requests` (mêmes contrôles et mêmes e-mails). Fonctions : compteurs et solde estimé, demandes en attente ou validées à venir, demande « du … au … », agenda du mois avec le **type de congé** (code) écrit sur chaque demi-journée et une légende. **Répartition** : les jours demandés se répartissent entre les types (`demandables`, avec leur `restant` dans `GET /api/mobile/summary`) par des boutons − / + (pas d'un jour, d'une demi-journée pour le reste), dans la limite du solde de chaque type ; l'envoi n'est possible que lorsque tous les jours sont répartis ; une demande `POST /api/requests` est créée par type, les premiers jours au premier type.
- **MOB-02** — **Abonnement à l'agenda du téléphone (ICS)** : `backend/ical.py`, migration `0013_calendrier_ics.sql` (table `calendar_tokens` : un lien actif par personne, **seul le haché SHA-256 du jeton est conservé**). `POST /api/mobile/calendar/link` crée (ou remplace) le lien — le jeton de 256 bits n'est renvoyé qu'ici —, `POST /api/mobile/calendar/revoke` l'arrête, `GET /api/mobile/calendar` donne l'état (actif, création, dernière lecture). `GET /api/ical/<jeton>.ics` (exposé par le frontend mobile sous `/cal/<jeton>.ics`) sert le flux **sans session** : 404 identique pour un jeton inconnu ou révoqué, limites par jeton (60/min), par adresse (240/min) et pour les jetons inconnus (30 en 10 min), nginx 30/min. Contenu : ma propre fiche, années en cours et suivante ; jour **validé** « ✅ Congé annuel » (`STATUS:CONFIRMED`), jour **demandé** « ⏳ … (en attente) » et annulation demandée « ⏳ … (annulation demandée) » (`STATUS:TENTATIVE`) ; refusé ou annulé : absent ; journées consécutives de même type et même état regroupées, demi-journées aux horaires `EXCHANGE_MORNING` / `EXCHANGE_AFTERNOON` ; **aucun motif sensible** (CM, GEM, CT, CP, SF, AI, ET, GR, SX : « Absence ») et le code n'apparaît nulle part dans le fichier (identifiants d'événements par empreinte) ; absences en heures et temps partiel exclus. Complète le module Outlook (EXCH) pour un téléphone sans compte de messagerie de la Ville.
- **MOB-03** — **Backend mobile séparé** : service `backend-mobile` de `docker-compose.yml` (même image, `command` gunicorn sur le port **8115**, `wsgi_mobile:application`, `CONGES_MODE=mobile`). `backend/mobile_mode.py` (activé par `CONGES_MODE=mobile`) place en tête des filtres une **liste blanche** : `POST /api/auth/login|logout`, `GET /api/me`, `GET /api/status`, `GET /api/mobile/summary|days|calendar|absences-rh`, `POST /api/mobile/calendar/link|revoke`, `POST /api/mobile/requests/<id>/cancel|cancel-request`, `POST /api/requests`, `POST /api/activation/*`, `GET /cal/<jeton>.ics` et `/api/ical/<jeton>.ics` ; tout le reste répond 404 sans toucher la base ; la page mobile est servie à la racine du conteneur (`conges-mobile-dmz/public` monté en lecture seule, `CONGES_MOBILE_PUBLIC`) ; cookie de session `conges_mobile` (`CONGES_COOKIE_PATH`), en-têtes de sécurité stricts. `wsgi_mobile.py` n'appelle pas `bootstrap()` : **ni migrations, ni relances, ni Outlook, ni préchauffage Sedit RH** (restent ceux du backend principal, dont dépend le démarrage). Le nginx du frontend interne (`frontend/nginx.conf.template`) publie **`/mobile/` pour les TESTS seulement** : active par défaut (`MOBILE_TEST=1`, `MOBILE_TEST=0` la coupe) mais seulement pour un nom d'hôte se terminant par `.ivry.local` (carte nginx `$mobile_test`), sinon 404 ; en production, la version mobile n'est exposée que par le frontend de la DMZ (`conges-mobile-dmz`, qui joint le backend mobile sur le port 8115). L'adresse préfixe retiré (`rewrite`), adresse résolue à l'usage (resolver Docker : nginx démarre même si le conteneur est arrêté), limite de 10 connexions par minute sur le login ; variable `MOBILE_BACKEND_URL` (défaut `http://backend-mobile:8115`). La page utilise des adresses relatives et un préfixe calculé (`BASE`) : elle fonctionne à la racine (DMZ) comme sous `/mobile/`. Poste sans Docker : `backend/run_mobile.py` (http://127.0.0.1:8115). Le frontend DMZ (`conges-mobile-dmz`) peut pointer sur ce backend plutôt que sur le backend complet.
- **API-04** — **Limitation** de débit (120 requêtes par minute et par clé) ; **journal** de chaque appel (méthode, chemin, statut, IP), sans contenu.
- **API-05** — **Documentation interactive** `/api-docs` (Swagger UI) et spécification `/api/v1/openapi.json`, vérifiée par un test (toute route `/api/v1` doit y figurer).
- **API-06** — **Supervision** : `GET /api/status` (public en interne) renvoie la **version**, l'état de l'application, de la base (latence), de l'APM et de Sedit RH (configurés ou non) et le mode d'authentification.
- **API-09** — La liste des fiches de l'API (`/api/v1/agents`) expose le **matricule** et la recherche `q` porte aussi sur le matricule.
- **VER-01** — **Version** : `GET /api/version` (publique, utilisée par l'écran de connexion) et `GET /api/changelog` (journal des versions) ; le numéro de version est affiché dans la barre du haut et sur l'écran de connexion ; un clic ouvre l'écran **Journal des versions** (nouveautés de chaque version) ; la version figure aussi dans la spécification Swagger.
- **API-07** — **CORS** fermé par défaut ; seules les origines de `CONGES_CORS_ORIGINS` sont autorisées.
- **API-08** — Les **routes internes** utilisées par l'écran (`/api/agents`, `/api/requests`, …) restent **non versionnées** et protégées par la session (voir 20).

---

## 18. Intégrations

| Service | Usage | Permission APM |
|---|---|---|
| **APM — Active Directory** | `POST /api/v1/ad/authenticate` (connexion), `GET /api/v1/ad/search` (recherche prédictive) | `ad_auth`, `ad_search` |
| **APM — Mail** | `POST /api/v1/mail/send` | `mail_send` |
| **PostgreSQL de la Ville** | stockage, schéma `conges` | rôle de base (voir 21) |
| **API Sedit RH** (`api-apps/sedit-rh`, port 3440) | **connexion testable depuis l'application** (14.8) : `SEDITRH_API_URL` et `SEDITRH_API_KEY` (clé `srh_live_…`, droits `agents:read`, `organisation:read` et `effectifs:read`, lecture seule) dans `.env`, état dans `/api/status` ; en développement l'API tourne en local ; le **matricule** sert de clé (`/api/v1/agents/{matricule}`) — le **nombre d'agents** (effectifs agrégés), puis, à la demande de l'administrateur, la **liste des agents en poste** (matricules, organisation, création d'agents — 14.9 et 14.10) ; le rapprochement est fait par nom et prénom, le matricule est enregistré dans l'application | clé Sedit RH |
| **Hub DSI** | non utilisé aujourd'hui ; piste : lire l'organisation (directions / services) et les agents plutôt que de les ressaisir `[H]` | clé `dsk_` |

- **INT-01** — Tous les appels à l'APM passent par un **module unique** (`apm.py`) ; une panne réseau ou une réponse 5xx est une erreur « service indisponible », jamais un « mot de passe faux ».
- **INT-02** — TLS vers l'APM : autorité de la Ville (`VILLE_CA_FILE`) ou, à défaut, certificat auto-signé accepté (`VILLE_ALLOW_SELF_SIGNED_CERTS`, **à éviter en production**).

---

## 19. Modèle de données (schéma `conges`)

| Table | Contenu |
|---|---|
| `users` | comptes : identifiant, `ad_login`, `matricule`, nom, e-mail, mot de passe haché, `admin`, rôle, responsable (`parent_id`), actif |
| `user_audit` | journal d'audit des comptes |
| `agents` | fiches : propriétaire, titulaire, valideur, nom, prénom, e-mail, `matricule`, année, `params` (JSON), `periods` (JSON), responsable d'unité |
| `cells` | demi-journées posées : (fiche, clé de demi-journée) → code |
| `settings` | paramétrage (JSON par clé : `general`, `codes`, `penibilites`, `matrix`, `jours_feries`, `vacances_scolaires`, `mail` — gabarits et mise en page des e-mails —, `journaux` — durées de conservation…) |
| `leave_requests` | demandes (type, code, demi-journées, jours, heures, dates, statut, valideur et responsable figés, commentaires, pièce jointe, champs d'annulation) |
| `leave_request_events` | historique des événements d'une demande |
| `hourly_absences` | absences en heures posées (fiche, date, code, horaires, heures, demande liée) |
| `api_keys` | clés API (empreinte, périmètres, IP, expiration, actif, dernier usage) |
| `login_logs` | journal des connexions (date, événement, identifiant, résultat, méthode, IP, navigateur) |
| `mail_logs` | journal des e-mails (date, destinataire, objet, message, statut, erreur, texte, demande) |
| `api_key_logs` | journal des appels API |
| `schema_migrations` | migrations appliquées (version, somme de contrôle) |

- **DON-01** — **Migrations** SQL numérotées (`backend/migrations/`), exécutées chacune dans une transaction ; une migration déjà appliquée ne doit jamais être modifiée (somme de contrôle).
- **DON-02** — Les **dates** sont du texte `AAAA-MM-JJ[ HH:MM:SS]` (heure de Paris) pour l'instant (D3) ; fuseau de la session de base : `Europe/Paris`.
- **DON-03** — **Suppression** d'un compte : supprime ses fiches (cascade) ; l'archivage à la place est noté au backlog.
- **DON-04** — **Suppression multiple** (Paramétrage > Utilisateurs) : cases à cocher par ligne (page affichée), confirmation listant les personnes, puis une suppression par compte avec les **mêmes règles que DON-03** (périmètre du valideur, jamais son propre compte) ; les refus sont listés après l'opération.
- **MEQ-10** — **Passer en valideur** (Mon équipe, `POST /api/my-agents/<id>/promote`) : réservé aux valideurs et administrateurs, dans leur périmètre, jamais pour soi-même ; l'agent devient valideur au niveau de son unité (plafonné sous celui de son propre valideur) ; journalisé. **Le responsable d'une unité en est automatiquement le valideur** (`org_units.head_user_id`, prioritaire sur les autres valideurs de l'unité) ; désigner un agent responsable le passe valideur ; dans les deux cas il **valide par défaut les agents de son unité** qui avaient le même valideur que lui (`adopt_unit_agents`), et un responsable resté agent est promu à l'affichage de Mon équipe. **Sélection multiple** (Ctrl/Cmd + clic sur les fiches) puis glisser-déposer : une requête `POST /api/my-agents/move` par personne, avec barre de progression. **Rattachement d'un agent Sedit RH** (glisser sur son valideur) : la liste des unités proposées est limitée aux entités de la direction du valideur (`GET /api/my-agents/<id>/unit`) ; **Repasser un valideur en agent** (`POST /api/my-agents/<id>/demote`, bouton « ↓ Agent ») : mêmes droits que la promotion ; ses subordonnés remontent sous son propre valideur, il perd la responsabilité d'unité, journalisé ; refusé pour un administrateur, pour soi-même et sans valideur. Chaque carte affiche son valideur ; une entité locale est signalée « locale ». **Période et fiche** : le bouton de la fenêtre « Définir la période » s'appelle « Créer la période » ; la carte d'une personne qui a une période porte le lien « Fiche congés » ; le report sur l'année suivante se fait uniquement pour toute l'équipe (« Reporter les périodes en N+1 »), plus par carte. Le bouton n'est proposé que lorsque l'année affichée est l'année en cours (report vers l'année suivante, pour les personnes qui n'ont pas encore cette fiche) ; sur toute autre année, il est masqué. **Solde de CET** (Sedit RH) — **cache** : migration `0011_cache_cet.sql` (table `sedit_cet_cache`, aussi gardée en mémoire) ; un solde de moins de 10 minutes est servi directement ; plus ancien, il est servi tel quel avec sa date (`as_of`) et recalculé en arrière-plan (`sedit_rh._refresh_cet_async`, un seul recalcul par matricule, pause d'une minute après un échec) ; jamais lu : lecture immédiate (`SeditError` si Sedit RH refuse ou est injoignable) ; « pas de CET » est mémorisé aussi. La carte de Mon équipe affiche la raison d'une indisponibilité. —  `GET /api/my-agents/cet?uids=…` (Mon équipe, personnes de mon périmètre seulement, 300 au plus) et `GET /api/agents/<id>/cet` (fiche, mêmes droits de lecture que la fiche) ; une requête `GET /api/v1/cet?matricules=…&ouvert=true` par lot de 100 matricules, résultat conservé 10 minutes ; carte « CET : N j » chargée après l'affichage de la page. **Solde initial par défaut** (y compris pour le contrôle d'une demande de congé, `_request_balance`, qui lit le solde tout de suite s'il n'est pas encore connu) : si le champ « Solde CET (j) » de la fiche est vide, le solde Sedit RH en mémoire le remplace dans le calcul (`/api/compute` avec `agent_id`, résumé du tableau de bord) ; une valeur saisie prime ; la clé `SEDITRH_API_KEY` doit avoir le droit `cet:read`, sinon la synthèse garde 0. **Valideur actuel** : `valideur_delegue` dans `GET /api/agents/<id>` (délégataire du valideur de la fiche si sa délégation est active) ; l'en-tête affiche « Valideur actuel » et « par délégation de … ». **Délégation automatique par défaut** : migration `0009_delegation_auto_par_defaut.sql` (`users.delegate_auto` à 1 par défaut et pour tous les comptes). **Absences Sedit RH dans la fiche** : `GET /api/agents/<id>/absences-rh` (mêmes droits que la fiche) ; codes CM, GEM, CT, CP, SF et dates seulement (jamais la nature détaillée) ; couleur claire, lecture seule, jours ouvrés sans saisie ; droit `absences:read` sur la clé. **Report des périodes et fin de contrat** : `POST /api/agents/duplicate` lit la date de départ de l'agent dans Sedit RH (`GET /api/v1/agents/<matricule>`) : la période de l'année suivante finit à cette date, un contrat terminé avant l'année n'est pas reconduit (`skipped`), Sedit RH indisponible = année entière signalée ; la page affiche un récapitulatif après le report. si l'unité propre à l'agent est hors de cette direction, il faut en choisir une.
- **DON-04** — **Pièces jointes** : stockées hors base, dans un volume (`/data/uploads`), sous un nom aléatoire.

---

## 20. API interne (utilisée par l'écran) — par domaine

| Domaine | Routes principales |
|---|---|
| Session | `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/me`, `POST /api/me/password` |
| Paramétrage | `GET/PUT /api/settings`, `POST /api/settings/reimport` |
| Utilisateurs | `GET/POST /api/users`, `PUT/DELETE /api/users/{id}`, `GET /api/users/audit` |
| Fiches | `GET/POST /api/agents`, `GET/PUT/DELETE /api/agents/{id}`, `POST /api/agents/{id}/clone`, `POST /api/agents/duplicate`, `PUT/DELETE /api/hourly/{id}` |
| Demandes | `GET/POST /api/requests`, `…/approve`, `…/refuse`, `…/cancel`, `…/cancel-request`, `…/cancel-approve`, `…/cancel-refuse`, `…/attachment`, `GET /api/requests/counts`, `GET /api/reminders` |
| Calcul et synthèses | `POST /api/compute`, `GET /api/dashboard`, `GET /api/hr-dashboard`, `GET /api/planning` |
| Administration | `/api/v1/admin/api-keys` (+ `/logs`), `/api/admin/act-as` (+ `/search`), `/api/admin/login-logs`, `/api/admin/mail-logs` (+ `/{id}`), `/api/admin/log-retention`, `/api/admin/mail-settings` (+ `/preview`, `/test`, `/reset`), `/api/admin/sedit-rh` (+ `/test`), `/api/admin/rh/organisation`, `/api/admin/rh/matricules` (+ `/apply`), `/api/admin/rh/import` (+ `/preview`) |
| Publiques | `/api/status`, `/api/version`, `/api/changelog`, `/api/v1/*` (clé), `/api-docs`, `/health` |

---

## 21. Sécurité, RGPD, audit, conservation

### 21.1 Acquis (v0.1.0)
Session signée (plus d'identité par en-tête), contrôle de périmètre côté serveur, requêtes SQL paramétrées, échappement systématique du texte côté écran + politique de contenu nginx,
mots de passe hachés (scrypt), pièces jointes sous nom aléatoire / extensions autorisées / 5 Mo, clés API hachées avec périmètres, IP et expiration, usurpation auditée, CORS fermé,
conteneur backend sans droits d'administrateur, dépendances sans vulnérabilité connue (audit du 2026-11-10).

### 21.2 Points ouverts (analyse du 2026-11-10 — **à traiter avant la mise en production**)
- **SEC-01** *(critique)* — Le compte `admin` a un mot de passe trivial (données de démonstration, D9) : à changer avant tout déploiement.
- **SEC-02** *(critique)* — L'application utilise le compte PostgreSQL `postgres` (superutilisateur) repris de `delib` : demander à la DSI un **rôle limité au schéma `conges`**.
- **SEC-03** *(élevé)* — TLS vers l'APM non vérifié : renseigner `VILLE_CA_FILE`.
- **SEC-04** *(élevé)* — La clé APM est celle de `delib` : en demander une **propre à l'application**.
- **SEC-05** *(élevé)* — Mots de passe initiaux générés prévisibles (`Conges` + 4 caractères + `!`) ; plus d'objet en mode AD, à corriger si le mode local est réutilisé.
- **SEC-06** *(élevé)* — Le champ « Identifiant AD » est modifiable par un valideur sur son périmètre : le réserver aux administrateurs et le rendre **unique**.
- **SEC-07** *(moyen)* — Limitation des connexions par adresse et en mémoire (pas de verrouillage par compte, dépend de `CONGES_PROXY_HOPS`) ; sessions sans révocation côté serveur ni délai d'inactivité.
- **SEC-08** *(moyen)* — Pièces jointes sans contrôle de contenu ni analyse antivirus, non chiffrées (justificatifs potentiellement médicaux).
- **SEC-09** *(moyen)* — Frontend DMZ : l'administration des utilisateurs et le paramétrage restent accessibles aux administrateurs depuis l'extérieur (pas de second facteur).
- **SEC-10** *(moyen)* — Dépendances et images Docker non épinglées.

### 21.3 RGPD `[H]`
- Données personnelles traitées : identité, e-mail, absences (les codes maladie / maternité relèvent de **données de santé**), pièces jointes.
- Les **journaux de connexions** (identifiant, adresse IP, navigateur) et d'**e-mails** (destinataire, texte) sont des données personnelles : leur durée de conservation est **réglable** (365 jours par défaut) avec **purge automatique**.
- À établir avec la DRH / le DPO : **registre des traitements**, **durées de conservation** (fiches, demandes, journal d'audit des comptes, journal des appels API — sans purge aujourd'hui), minimisation des données exposées par l'API (`absences:read` révèle les codes).
- **Audit** : journal des comptes et historique des demandes conservés ; pas de purge automatique.

---

## 22. Architecture, déploiement et DMZ

```
 Utilisateurs internes ─▶ frontend nginx (8111) ─┐
                                                  ├─▶ backend Flask / gunicorn (8110) ─▶ PostgreSQL (schéma conges)
 Utilisateurs externes ─▶ frontend DMZ (8112) ───┘          │
                                                             └─▶ API centrale APM (AD, mail)
```

- **DEP-01** — `docker-compose.yml` : backend (gunicorn, 1 processus × 8 threads, utilisateur non privilégié, volume `conges_data`) + frontend nginx ; `docker-compose.dmz.yml` : frontend DMZ seul.
- **DEP-02** — Le backend n'est publié que sur la machine locale (`BACK_BIND=127.0.0.1`) tant qu'aucun frontend distant ne doit le joindre ; il faudra l'ouvrir à l'adresse du frontend DMZ par pare-feu.
- **DEP-03** — Frontend interne : en-têtes de sécurité, politique de contenu stricte, limitation des connexions (10/min) ; **frontend DMZ** : 5 connexions/min, routes `/api/v1`, `/api-docs`, `/api/status`, `/api/admin/act-as` **invisibles** (404).
- **DEP-04** — Le HTTPS est assuré par le reverse-proxy de la Ville ; `CONGES_PROXY_HOPS` (1 avec nginx seul, 2 avec le proxy de la Ville) conditionne l'adresse IP vue par l'application.
- **DEP-08** — **Réseau Docker** : sous-réseau **fixe** par déploiement (`CONGES_SUBNET`, `10.77.110.0/24` par défaut ; `CONGES_DMZ_SUBNET`, `10.77.112.0/24` pour le frontend DMZ), pour ne pas dépendre des plages automatiques de Docker, épuisées sur les serveurs très utilisés (« all predefined address pools have been fully subnetted ») ; il ne doit chevaucher aucun réseau ni route existants.
- **DEP-05** — Un seul processus serveur : relances automatiques et limitation de débit sont en mémoire de processus.
- **DEP-06** — **Non vérifié** : les images n'ont pas encore été construites ni lancées sur un serveur Docker.
- **DEP-07** — Les sauvegardes de la base relèvent de la DSI ; le volume des pièces jointes est à sauvegarder avec.

---

## 22 bis. Module exchange : agenda Outlook (Microsoft Graph)

- **EXC-01** — **Choix de l'agent** : carte « Agenda Outlook » dans « Ma synthèse » (`GET/PUT /api/exchange`, `POST /api/exchange/sync`) ; case décochée par défaut (`users.exchange_sync`) ; personnelle (refusée en mode « en tant que ») ; masquée tant que l'administrateur n'a pas configuré les identifiants Graph.
- **EXC-02** — **Ce qui est écrit** : pour chaque jour d'absence (codes de `ABSENCE_CODES`), un événement dont le titre est **« ABSENT »**, disponibilité « Absent du bureau » (`showAs = oof`), « privé », sans rappel, sans corps ni participants ; une demi-journée donne un événement sur le matin (`EXCHANGE_MORNING`, 08:30-12:30) ou l'après-midi (`EXCHANGE_AFTERNOON`, 13:30-17:30), une journée complète un événement « toute la journée ».
- **EXC-03** — **Télétravail** : un jour (ou une demi-journée) `TT` devient un événement « Télétravail » en disponibilité « Travaille ailleurs » (`workingElsewhere`). **Jours demandés** : une demande en attente de validation (`leave_requests.status = 'en_attente'`) donne un événement « ABSENT » en disponibilité « Provisoire » (`showAs = tentative`, `kind = PROV`) ; la validation le remplace par « Absent du bureau », le refus ou l'annulation le supprime ; une case déjà posée dans la fiche prévaut sur une demande ; seules les absences sont concernées (pas le télétravail).
- **EXC-04** — **Suivi** : table `exchange_events` (une ligne par événement créé) ; la synchronisation ne touche que les événements qu'elle a créés ; fenêtre du 1er janvier de l'année en cours à la fin de l'année suivante (les absences déjà passées de l'année sont reprises) ; événements des années précédentes laissés dans l'agenda. Elle s'exécute à l'activation, à la demande, puis toutes les `EXCHANGE_INTERVAL_MIN` minutes (10 par défaut) ; désactiver retire les événements. **Mise à jour au fil de l'eau** : une demande, une validation, un refus, une annulation ou une modification de fiche lance la synchronisation de l'agent concerné en arrière-plan ; un événement supprimé dans Outlook est recréé (l'API Ville liste les événements de la période : `GET /api/v1/o365/calendar/events`).
- **SYN-05** — **Soldes prévisionnels** : la synthèse (fiche et « Ma synthèse ») indique, pour chaque solde, le restant si toutes les demandes en attente étaient validées (calcul `/api/compute`, champ `prevision`, absent quand rien n'est en attente). Présentation : une ligne par solde, détail replié (clic sur le titre) ; le prévisionnel n'est affiché que s'il diffère du solde actuel.
- **SYN-06** — **Autres** : la synthèse (fiche et « Ma synthèse ») totalise, par type d'absence (CM, GEM, CT, CP, SF), les jours ouvrés saisis dans Sedit RH sur l'année de la fiche (week-ends et jours fériés exclus), à titre d'information : ils ne modifient aucun solde.
- **EXC-05** — **Passage par l'API Ville (APM)** : les appels utilisent `APM_API_URL` / `APM_API_KEY` (clé `X-API-KEY` de l'application), jamais Microsoft directement. Route d'agenda attendue (chemin réglable : `EXCHANGE_APM_EVENTS_PATH`, par défaut `/api/v1/o365/calendar/events`) : `POST` avec `{mailbox, subject, start, end, isAllDay, showAs, isReminderOn, sensitivity}` qui retourne `{id}` ; `DELETE <chemin>/<id>?mailbox=<e-mail>` qui retourne 204 ; l'APM porte les droits Microsoft (`Calendars.ReadWrite`). Cette route a été **ajoutée à l'APM** (`C:\dev\APM`, `backend/routes/proxy.js`, permission `o365_calendar`, boîte `mailbox` obligatoire, champs filtrés) ; tant qu'elle n'est pas déployée sur `https://api.ivry.local` (absente de `/swagger.json`), l'application le détecte (`exchange.availability`, vérifié toutes les 10 minutes), la carte de Ma synthèse indique « pas encore disponible » et rien n'est envoyé. Nouvelles tentatives sur 429/503 ; une panne est mémorisée (`users.exchange_error`) et affichée.

## 23. Organisation du code et qualité

```
backend/    app.py (routes internes), rules.py (calcul), pg_db.py / db.py (accès PostgreSQL), config.py, apm.py, mailer.py, reminders.py,
            api_v1.py, api_keys.py, act_as.py, admin_settings.py (journaux, e-mails), audit_logs.py, mail_templates.py,
            sedit_rh.py (API Sedit RH), rh_import.py (matricules, organisation RH, création d'agents), openapi_spec.py, ratelimit.py, http_utils.py, version.py, wsgi.py, migrations/, tests/, Dockerfile
frontend/   public/ (index.html, app.js, style.css), nginx.conf.template, nginx.dmz.conf.template, proxy_params_conges, Dockerfile
racine      docker-compose.yml, docker-compose.dmz.yml, .env.example, README.md, MANIFEST.md, CHANGELOG.md, modifications.md, CLAUDE.md
            (backend/version.py = source unique de la version)
```

- **QUA-01** — **49 tests automatiques** : régressions métier, authentification locale / AD simulée, mails (APM simulée), clés API, documentation, « se connecter en tant que » (sur un schéma PostgreSQL temporaire, créé puis supprimé) et **cohérence du versionnage** (`test_version.py`, sans base), journaux, gabarits d'e-mails, matricule.
- **QUA-02** — Dette connue : fichiers volumineux (`app.py`, `app.js`, `rules.py`), pas de lint, pas de typage ; le découpage par modules `modules/<feature>/` du guide reste à faire.
- **QUA-03** — Les 114 consultations de référence (tableaux de bord, planning, fiches, demandes…) ont été **comparées avant / après** la migration vers PostgreSQL : résultats identiques.

---

## 24. Écarts avec le guide et dette technique

| # | Écart | Réponse prévue |
|---|---|---|
| T1 | Backend Python/Flask au lieu de Node/Express | D1 : décision de principe à confirmer avec la DSI (Q1) |
| T2 | Frontend sans framework au lieu de React/TypeScript | idem |
| T3 | Dates en texte | étape dédiée `TIMESTAMPTZ` (Q2) |
| T4 | Routes internes non versionnées | acceptable tant que le frontend est livré avec le backend |
| T5 | Fichiers > 300 lignes | découpage progressif |
| T6 | Organisation Ville non lue via le Hub DSI | Q6 |
| T7 | Anciens lanceurs `serve.py` / `demarrer-prototype.vbs` | obsolètes, à supprimer |

---

## 25. Critères d'acceptation clés (exemples testables)

- **ACC-01** — Un agent dont le solde CA restant est de 1 jour ne peut **pas** demander 2 jours de CA : la demande est refusée (« Solde insuffisant : il resterait −1 j »).
- **ACC-02** — Une demande d'absence validée écrit les demi-journées dans le calendrier ; son annulation approuvée les supprime.
- **ACC-03** — Un valideur ne peut **pas** valider une demande dont le valideur assigné est son **supérieur** ou un compte hors de son périmètre ; son supérieur et l'administrateur le peuvent.
- **ACC-04** — Un cassage réserve le jour dès la soumission, crédite 7 h à la validation, et ne peut plus être annulé si des heures ont été consommées.
- **ACC-05** — Les RCH sont consommées dans l'ordre d'ancienneté et ne sont plus utilisables après 6 mois.
- **ACC-06** — Un agent voit le planning de son équipe **sans le motif** des absences de ses collègues.
- **ACC-07** — Une clé API sans le périmètre `balances:read` reçoit **403** sur `/api/v1/agents/{id}/balance` ; une clé expirée ou désactivée reçoit **401**.
- **ACC-08** — En mode AD, un agent se connecte avec son mot de passe **Ville** (son mot de passe local est refusé) ; si l'APM est indisponible, un administrateur peut encore se connecter avec son mot de passe local.
- **ACC-09** — Pendant « Se connecter en tant que », les modifications sont attribuées dans le journal à l'administrateur réel, et le changement de mot de passe du compte usurpé est refusé.
- **ACC-10** — Une fiche dupliquée vers l'année suivante conserve les paramètres (hors dates d'arrivée et de départ) et **aucune** absence saisie.

---

## 26. Questions ouvertes

| # | Question | Pour |
|---|---|---|
| **Q1** | La DSI accepte-t-elle de maintenir une application Python/Flask, ou la réécriture Node/React est-elle exigée avant la production ? | DSI |
| **Q2** | Quand convertir les dates en `TIMESTAMPTZ` (impact sur les calculs) ? | DSI / dev |
| **Q3** | Comment faire correspondre les comptes agents (identifiant généré « initiale + nom ») aux identifiants AD de la Ville ? Import en masse de l'« Identifiant AD » depuis l'annuaire ? | DRH / DSI |
| **Q4** | Les agents doivent-ils recevoir un mail à la validation / au refus de leurs demandes ? Alerte RCH à 30 jours ? | DRH |
| **Q5** | Faut-il une **délégation de validation** (remplaçant temporaire) et/ou une validation **multi-niveaux** séquentielle ? | DRH |
| **Q6** | La hiérarchie doit-elle être lue dans le Hub DSI (organisation, agents) plutôt que saisie ? | DSI / DRH |
| **Q7** | Quelles routes ouvrir ou fermer depuis la DMZ ? L'administration depuis l'extérieur nécessite-t-elle un second facteur ? | DSI / DRH |
| **Q8** | Durées de conservation des fiches, demandes, journaux, pièces jointes ; qui est le responsable de traitement ? | DRH / DPO |
| **Q9** | Les justificatifs (pièces jointes) peuvent-ils contenir des données de santé ? Faut-il un stockage chiffré / antivirus ? | DRH / DPO |
| **Q10** | Quel rôle PostgreSQL dédié, quelle clé APM propre, quel certificat (`VILLE_CA_FILE`) pour la production ? | DSI |
| **Q11** | Quelles applications consommeront l'API `/api/v1` et avec quels périmètres ? | DRH / DSI |
| **Q12** | Les niveaux hiérarchiques doivent-ils devenir configurables ? | DRH |
| **Q13** | Sedit RH, suite : synchroniser **automatiquement** les agents et l'organisation (arrivées, départs, changements de service) plutôt qu'à la demande ? Reprendre d'autres informations (fonction « responsable de secteur » pour désigner les valideurs d'unité) ? Quelle clé et quelle adresse en production ? | DRH / DSI |
| **Q16** | Comptes d'unité créés automatiquement : qui doit en être le titulaire (valideur) et comment le désigner (fonction RH, saisie à la main) ? Les agents sans e-mail dans l'AD doivent-ils être refusés plutôt que créés sans e-mail ? | DRH |
| **Q17** | Faut-il remplacer les comptes d'unité hérités (« DIR-… », « SRV-… », créés avant les rôles) par des **personnes valideurs** rattachées à leur unité, et la recherche d'un agent peut-elle aussi proposer le valideur de l'unité ? | DRH |
| **Q18** | Dans « Mon équipe », faut-il refuser de placer un agent sous une personne dont l'unité n'est pas égale ou supérieure à celle de l'agent ? | DRH |
| **Q15** | L'en-tête des e-mails (gabarit institutionnel de l'APM) doit-il pouvoir être personnalisé par application ? Cela suppose que l'APM accepte un paramètre d'en-tête (aujourd'hui : expéditeur et pied de page seulement). | DSI |
| **Q14** | Quels autres e-mails automatiques souhaite-t-on (validation / refus à l'agent, annulation, alerte RCH) — voir Q4 — pour les ajouter au registre des gabarits ? | DRH |

---

## 27. Hypothèses posées

- **H1** — Les valeurs d'un jour = 7 heures sont uniformes pour tous les agents (quelle que soit la quotité) `[H]`.
- **H2** — Les données actuelles sont de démonstration (D9) ; aucune reprise de données réelles n'est à préparer pour l'instant.
- **H3** — Le format des identifiants AD de la Ville correspond à l'identifiant « sAMAccountName » renvoyé par l'APM `[H]`.
- **H4** — Un agent n'a qu'un seul valideur à la fois ; la validation par plusieurs niveaux successifs n'est pas requise (Q5).
- **H5** — La charge attendue (quelques centaines d'agents) est compatible avec un seul processus serveur.

---

## 28. Backlog (repris de `AMELIORATIONS-A-ETUDIER.md` et de l'analyse de sécurité)

**Sécurité et fiabilité** — traiter SEC-01 à SEC-10 ; archivage plutôt que suppression des comptes ; changement de mot de passe obligatoire à la première connexion ; expiration de session ; empêcher les cycles hiérarchiques (déjà contrôlé à la création).
**Circuit et notifications** — mails à l'agent (validation / refus / annulation) ; alerte d'expiration RCH à 30 jours ; délégation de validation ; pièce jointe pour les déclarations RCH ; validation multi-niveaux.
**Administration** — import CSV / annuaire des comptes ; organigramme visuel ; actions groupées (changer un responsable, désactiver plusieurs comptes) ; **exports Excel / CSV** ; indicateurs RH supplémentaires.
**À reprendre plus tard (mis de côté le 2026-11-10, voir Q13 et Q16)** — désigner automatiquement le titulaire des comptes d'unité créés depuis Sedit RH (piste : la fonction RH « Responsable de secteur ») ; décider s'il faut refuser la création d'un agent dont l'e-mail est introuvable dans l'AD plutôt que de le créer sans e-mail ; synchronisation automatique (et non plus à la demande) des agents et de l'organisation.
**Évolutions lourdes** — niveaux hiérarchiques configurables ; matrice de droits plus fine (consulter / valider / gérer) ; responsive mobile et accessibilité ; conversion des dates en `TIMESTAMPTZ` ; migration éventuelle vers la stack du guide ; versionnement des routes internes.

---

## 29. Journal des versions

La convention de versionnage est celle de l'application delib : **0.x.y** avant la production — **x** (mineure) : ajout d'un module ou d'une fonctionnalité ; **y** (correctif) : correction ou
amélioration sans nouveau module ; **1.0.0** : mise en production. Chaque version porte sa **date de livraison**.

- Le **journal détaillé** est `CHANGELOG.md` ; la **source unique de la version** est `backend/version.py` (affichée dans l'application, `/api/version`, `/api/status`, Swagger).
- **À chaque nouvelle version**, la documentation est mise à jour : `CHANGELOG.md`, `backend/version.py`, **le présent manifeste** (en-tête de statut, sections concernées, questions ouvertes), `modifications.md` (explication pour le métier) et, si nécessaire, `README.md`.
  Un test automatique vérifie la cohérence entre `version.py`, `CHANGELOG.md` et ce manifeste. La procédure complète est dans `CLAUDE.md`.

| Version | Date | Contenu |
|---|---|---|
| **0.21.2** | 2026-11-17 | Durcissement de l'accès sans AD : journal des SMS complet (`activation._sms`, canal « sms » de `mail_logs`), `remember.revoke_all` aussi lors du changement de mot de passe par un administrateur, limite nginx `zone=act` (12 requêtes/minute) sur toutes les entrées ; contrôle de santé du backend mobile sur la page. |
| **0.21.1** | 2026-11-17 | Version mobile : absences Sedit RH dans l'agenda (`GET /api/mobile/absences-rh`), fenêtres centrées, zoom de secours en « version pour ordinateur », messages d'erreur de l'empreinte, avertissement d'adresse interne. |
| **0.21.0** | 2026-11-17 | Agents sans compte AD : activation par code (valideur) + SMS + e-mail facultatif + mot de passe, mot de passe oublié par SMS, confirmations par SMS sans e-mail, « se souvenir de moi », verrou biométrique local ; documentation `docs/ACCES_AGENTS_SANS_AD.md` et diagrammes BPMN `docs/bpmn/`. |
| **0.20.1** | 2026-11-17 | L'adresse `/mobile/` du frontend interne est réservée aux tests (`MOBILE_TEST`, noms en `.ivry.local`). |
| **0.20.0** | 2026-11-17 | Backend mobile séparé (`backend-mobile`, port 8115) accessible sous `/mobile/` : `backend/mobile_mode.py`, `wsgi_mobile.py`, `run_mobile.py`. |
| **0.19.0** | 2026-11-17 | Version mobile : frontend dédié `conges-mobile-dmz/` (DMZ uniquement, liste blanche de douze routes) et routes `GET /api/mobile/summary` / `GET /api/mobile/days` ; nom d'affichage unique « Prénom NOM » (`db.user_label`, `db.ad_display`). |
| **0.18.2** | 2026-11-17 | Tableau de bord regroupé par entité (`unit_label`, `unit_head` dans `GET /api/dashboard`) ; personnes sans période listées (`sans_periode`, `motif` : « Fiche non créée » ou « Période incomplète ») ; recherche rapide d'une personne en modale pour les administrateurs (`GET /api/admin/agent-search`, bouton 🔍 / Ctrl+K : valideur, délégataire, comptes application et AD, fiches). |
| **0.18.1** | 2026-11-17 | Mon équipe : alerte des personnes dont le lien Active Directory est incomplet (`no_ad` : pas d'identifiant AD, ou `no_email` : pas d'adresse e-mail ; repères « ⚠ AD » / « ⚠ e-mail » ; « Recherche AD » enregistre aussi le nom AD). |
| **0.18.0** | 2026-11-17 | Nom AD affiché par défaut (nom RH en italique dessous), API `GET /api/v1/managers`, Mon équipe (fin de contrat, solde estimé, délégation en pointillé) et en-tête refaits, boutons d'e-mail compatibles ancien Outlook. |
| **0.17.8** | 2026-11-17 | Bloc « Autres » (absences Sedit RH) dans la synthèse. |
| **0.17.7** | 2026-11-17 | Panneau de synthèse compact. |
| **0.17.6** | 2026-11-17 | Agenda Outlook à jour à chaque demande, soldes prévisionnels. |
| **0.17.5** | 2026-11-17 | Jours demandés provisoires dans Outlook, CET contrôlé avec Sedit RH. |
| **0.17.4** | 2026-11-17 | Report des périodes : seulement l'année suivante. |
| **0.17.3** | 2026-11-16 | Solde de CET en cache, agenda Outlook via l'API Ville. |
| **0.17.2** | 2026-11-16 | Exchange passe par l'API Ville (route d'agenda à ajouter côté APM). |
| **0.17.1** | 2026-11-16 | Ma synthèse pour tous (valideurs et administrateurs : entrée « Ma synthèse », route `#/synthese`). |
| **0.17.0** | 2026-11-16 | Module exchange : absences dans l'agenda Outlook. |
| **0.16.0** | 2026-11-16 | Mon équipe : valideur, unité entière, progression ; identifiants AD ; directeur rattaché à sa direction ; connexion par l'identifiant AD. |
| **0.15.0** | 2026-11-16 | Utilisateurs : tableau compact (case Admin en colonne, pas de mot de passe en mode AD) et suppression multiple. |
| **0.14.4** | 2026-11-16 | Tableau de bord RH réservé aux administrateurs. |
| **0.14.3** | 2026-11-16 | Mon équipe : les entités d'abord, puis leurs membres. |
| **0.14.2** | 2026-11-16 | Planning : titres de groupe par entité. |
| **0.14.1** | 2026-11-16 | Planning : raison pour mon équipe, présence pour les autres, encadrants visibles. |
| **0.14.0** | 2026-11-16 | Mon équipe : unité de chaque agent, unités locales et responsable d'unité. |
| **0.13.2** | 2026-11-16 | Barre du haut adaptée aux fenêtres étroites. |
| **0.13.1** | 2026-11-16 | API Sedit RH : toutes les unités publiées. |
| **0.13.0** | 2026-11-16 | Années dans la fiche, report des périodes, équipes manquantes de Sedit RH. |
| **0.12.1** | 2026-11-16 | Fiche : unité modifiable, e-mail et matricule verrouillés ; Mon équipe plus large. |
| **0.12.0** | 2026-11-16 | Mon équipe remplace Mes fiches : entités et périodes visuelles. |
| **0.11.5** | 2026-11-16 | Mes congés : demandes pour tous, jamais de validation directe. |
| **0.11.4** | 2026-11-16 | Mon équipe : Dupliquer pour l'année suivante. |
| **0.11.3** | 2026-11-16 | Tableau de bord RH : entités et responsables. |
| **0.11.2** | 2026-11-16 | Fiche plus compacte ; « Mes congés » en consultation. |
| **0.11.1** | 2026-11-16 | Onglets de fiches : « + » ouvre des fiches de l'équipe. |
| **0.11.0** | 2026-11-16 | E-mails avec boutons, délégation des valideurs, Mon équipe en deux niveaux. |
| **0.10.2** | 2026-11-16 | Planning : jours non validés en pointillé. |
| **0.10.1** | 2026-11-16 | Mes congés : sa propre fiche même pour un valideur. |
| **0.10.0** | 2026-11-16 | Mon équipe par défaut, « Voir tout » pour les administrateurs, recherche AD. |
| **0.9.1** | 2026-11-16 | E-mails des valideurs : compte AD retenu et alerte « sans e-mail ». |
| **0.9.0** | 2026-11-16 | Menu « Mes congés » et « Mon équipe ». |
| **0.8.1** | 2026-11-16 | Fiches : « Valideur » et noms Prénom NOM. |
| **0.8.0** | 2026-11-16 | Jours travaillés par période, entités et responsables dans « Mes fiches », noms corrigés. |
| **0.7.0** | 2026-11-16 | Fiche congés = première période de paramètres, agents hors unité, jours hors période grisés. |
| **0.6.2** | 2026-11-16 | Mes agents : sélection multiple pour le glisser-déposer. |
| **0.6.1** | 2026-11-16 | Connexion : identifiant insensible à la casse. |
| **0.6.0** | 2026-11-16 | Mes agents (glisser-déposer depuis Sedit RH) et règles métier consultables. |
| **0.5.0** | 2026-11-16 | Trois rôles et unités Sedit RH : création d'une personne depuis Sedit RH et l'Active Directory. |
| **0.4.0** | 2026-11-10 | Organisation Sedit RH, matricules et création d'agents depuis la base RH. |
| **0.3.0** | 2026-11-10 | Test de l'API Sedit RH et nombre d'agents. |
| **0.2.3** | 2026-11-10 | E-mails : adresse du test d'envoi saisissable à côté du bouton. |
| **0.2.2** | 2026-11-10 | Déploiement Docker : sous-réseau fixe configurable. |
| **0.2.1** | 2026-11-10 | E-mails : activation réglable dans l'application, tests toujours possibles, écran Messages en liste. |
| **0.2.0** | 2026-11-10 | Paramétrage général, journaux, gabarits d'e-mails et matricule : menu Paramétrage à sous-sections (utilisateurs et clés API déplacés), journal des connexions, journal des e-mails, gabarits des e-mails automatiques et mise en page commune (expéditeur, en-tête, signature, pied de page), matricule, mot de passe masqué pour les comptes AD, connexion Sedit RH préparée. |
| **0.1.0** | 2026-11-10 | Première version versionnée : application du prototype DRH mise en conformité avec le guide de la Ville (sessions signées, PostgreSQL, AD et mail par l'APM, API `/api/v1`, clés API, `/api/status`, Swagger, « se connecter en tant que », Docker, frontend DMZ, organisation `backend/` / `frontend/`), manifeste et journal des versions. |
