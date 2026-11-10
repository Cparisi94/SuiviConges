# MANIFEST — Suivi des congés : gestion des congés, RTT et heures des agents

> **Statut : v0.1.0 — manifeste « tel que construit » (as-built), établi le 2026-11-10.**
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
| **D11** | **Aucun import/export Excel** n'est prévu par l'application en production (l'import de paramètres depuis le classeur reste un outil d'amorçage). | 14.2 |

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
| Tests sur la logique critique | **Partiel** : 33 tests (voir 23) |

---

## 4. Glossaire et acteurs

### 4.1 Glossaire métier

| Terme | Sens dans l'application |
|---|---|
| **Fiche** | Dossier annuel d'un agent : paramètres + calendrier + demandes + soldes. Une fiche = un agent × une année. |
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
| Tableau de bord RH | non | oui | oui |

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
- **FIC-01** — Identité : nom et prénom (en majuscules), e-mail (obligatoire, valide).
- **FIC-02** — Rattachement : **propriétaire** (un valideur actif), **valideur** de la fiche, année, indicateur « responsable d'unité ».
- **FIC-03** — Paramètres de calcul : **pénibilité**, **durée hebdomadaire** (35 h … 38 h), **quotité** (100 % … 50 %), **jours travaillés par semaine**
  (5 … 1), **date d'arrivée**, **date de départ**, **reliquat** (jours), **solde CET**.
- **FIC-04** — **Périodes multiples** : une fiche peut comporter plusieurs périodes de paramètres dans l'année (changement de quotité, de durée…) ;
  les droits sont calculés par période puis cumulés.
- **FIC-05** — À la création d'une fiche, un **compte agent** est créé automatiquement (identifiant = initiale du prénom + nom en majuscules,
  suffixe numérique en cas de doublon), rattaché au propriétaire. En mode AD, l'« Identifiant AD » du compte doit correspondre à l'identifiant Ville (voir Q3).
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
- **TDB-03** — **Tableau de bord RH** (non-agents) : **taux d'absence** = jours d'absence ÷ capacité de travail, global, **par direction / service** et en **arbre hiérarchique** ;
  **demandes en retard** (en attente depuis plus de 3 jours) ; **RCH proches de l'expiration**. Les heures d'absence sont converties en jours (7 h = 1 jour).
- **TDB-04** — Si le calcul d'une fiche échoue (fiche incomplète), la ligne affiche l'erreur **sans casser** le tableau.

---

## 13. Planning mensuel

- **PLA-01** — Vue d'un **mois** : les absences de chaque agent jour par jour, avec **week-ends, jours fériés et vacances scolaires** ; **totaux par agent**.
- **PLA-02** — Portée : « mes fiches » ou « **toutes les fiches de mon périmètre** » regroupées par niveau hiérarchique (dégradés de brique du plus sombre — direction — au plus clair — secteur).
- **PLA-03** — Les agents voient leur équipe avec les **motifs masqués** (DRO-03).
- **PLA-04** — **Impression** du planning en A4 paysage, sans la synthèse mensuelle.

---

## 14. Administration

### 14.1 Utilisateurs
- **ADM-01** — Création, modification, désactivation, suppression de comptes (voir 5) ; l'administrateur peut modifier l'identifiant, le rôle, le rattachement ; un valideur gère les paramètres et le mot de passe des comptes de son périmètre.
- **ADM-02** — Champ **« Identifiant AD »** : identifiant Ville utilisé pour la connexion AD lorsqu'il diffère de l'identifiant de l'application.
- **ADM-03** — **Journal d'audit des comptes** : création, changement d'identifiant, de rôle, de responsable, d'activation, de mot de passe (jamais la valeur), suppression, usurpation (début / fin), avec l'acteur réel.
- **ADM-04** — Garde-fous : on ne peut pas retirer ses propres droits administrateur ni désactiver son propre compte ; recherche, filtres (rôle, actif) et pagination dans la liste.

### 14.2 Paramétrage (administrateur)
- **PAR-01** — Codes d'absence (libellé, couleur, présence dans la grille), pénibilités, durées hebdomadaires, quotités, jours hebdomadaires, table « durée → RTT », **matrice de droits**, jours fériés, vacances scolaires, **année par défaut**.
- **PAR-02** — Le paramétrage est stocké en base (table `settings`) ; un **réimport depuis le classeur Excel** (copié dans `source/`) existe comme outil d'amorçage (D11).

### 14.3 Clés API
- **ADM-10** — Écran **Clés API** (administrateur) : création (nom, périmètres, IP autorisées, expiration), désactivation, suppression, **journal des appels** (voir 17).

### 14.4 « Se connecter en tant que »
- **ACT-01** — Réservé aux **administrateurs**. Bouton « En tant que… » : **recherche prédictive** (≥ 2 lettres) dans l'**AD** via l'APM, complétée par les comptes de l'application (utilisables si l'AD est indisponible).
- **ACT-02** — L'administrateur **agit avec exactement les droits de l'agent**, sans connaître son mot de passe ; un **bandeau** rappelle l'usurpation avec « Revenir à mon compte ».
- **ACT-03** — **Interdits** : un autre administrateur, un compte désactivé, soi-même, un agent sans compte dans l'application (grisé avec le motif), l'enchaînement de deux usurpations, le changement de mot de passe du compte usurpé.
- **ACT-04** — **Traçabilité** : début et fin journalisés ; les modifications de comptes et les décisions sur les demandes faites pendant l'usurpation sont attribuées à l'**administrateur réel** avec la mention « en tant que ».

---

## 15. Authentification et sessions

- **AUT-01** — **Mode local** (`CONGES_AUTH_MODE=local`) : mots de passe de l'application (hachage scrypt, 8 caractères minimum, changement par l'utilisateur).
- **AUT-02** — **Mode AD** (`ad`) : le mot de passe est vérifié par l'AD via l'APM (`POST /api/v1/ad/authenticate`) avec l'« Identifiant AD » ou l'identifiant ; le compte doit **exister dans l'application** (rôle, rattachement).
- **AUT-03** — **Compte de secours** : en mode AD, les **administrateurs** acceptent aussi leur mot de passe local ; les autres reçoivent « service d'authentification indisponible » (503) si l'APM est en panne.
- **AUT-04** — Le changement de mot de passe dans l'application est **refusé** aux comptes gérés par l'AD.
- **AUT-05** — **Session** : cookie signé (`HttpOnly`, `SameSite=Lax`, `Secure` en HTTPS), valable 10 h ; l'identité n'est jamais lue dans un en-tête fourni par le client.
- **AUT-06** — **Limitation des essais** : 8 échecs en 15 minutes par adresse (+ 10 par minute côté nginx) ; message d'erreur identique pour un compte inconnu et un mot de passe faux.
- **AUT-07** — **Premier démarrage** : un compte `admin` est créé avec `CONGES_INITIAL_ADMIN_PASSWORD` ou un mot de passe aléatoire affiché une fois.

---

## 16. Notifications

- **NOT-01** — Chaque **nouvelle demande** envoie un **mail au valideur** : agent, code, demi-journées, nombre de jours, commentaire, liens vers la fiche et vers les demandes à valider (`CONGES_BASE_URL`).
- **NOT-02** — **Relance quotidienne** : un mail par valideur listant ses demandes en attente depuis **plus de 3 jours**, au plus une fois par jour.
- **NOT-03** — Les mails passent par l'APM (corps HTML échappé, pied de page en trois lignes + couleur paramétrables) ; **un échec d'envoi n'empêche jamais** l'enregistrement d'une demande ; l'envoi est désactivé tant que `CONGES_MAIL_ENABLED` n'est pas à 1.
- **NOT-04** — Non couvert : mail à l'agent lors de la validation / du refus, alerte RCH à 30 jours par mail (backlog).

---

## 17. API externe, clés et supervision

- **API-01** — **API `/api/v1` en lecture seule** : `GET /agents`, `GET /agents/{id}`, `GET /agents/{id}/balance`, `GET /absences`, `GET /requests`. Listes **paginées** (`limit`, `offset`), erreurs `{ "error": … }`.
- **API-02** — **Clés** `cgk_` + 64 caractères hexadécimaux, en-tête `X-API-Key` (ou `Authorization: Bearer`), **affichées une seule fois**, stockées hachées (SHA-256).
- **API-03** — **Périmètres** : `agents:read`, `balances:read`, `absences:read`, `requests:read` (ou `*`) ; **IP/réseaux autorisés** et **expiration** facultatifs ; désactivation immédiate.
- **API-04** — **Limitation** de débit (120 requêtes par minute et par clé) ; **journal** de chaque appel (méthode, chemin, statut, IP), sans contenu.
- **API-05** — **Documentation interactive** `/api-docs` (Swagger UI) et spécification `/api/v1/openapi.json`, vérifiée par un test (toute route `/api/v1` doit y figurer).
- **API-06** — **Supervision** : `GET /api/status` (public en interne) renvoie la **version**, l'état de l'application, de la base (latence), de l'APM (configurée ou non) et le mode d'authentification.
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
| **Hub DSI** | non utilisé aujourd'hui ; piste : lire l'organisation (directions / services) et les agents plutôt que de les ressaisir `[H]` | clé `dsk_` |

- **INT-01** — Tous les appels à l'APM passent par un **module unique** (`apm.py`) ; une panne réseau ou une réponse 5xx est une erreur « service indisponible », jamais un « mot de passe faux ».
- **INT-02** — TLS vers l'APM : autorité de la Ville (`VILLE_CA_FILE`) ou, à défaut, certificat auto-signé accepté (`VILLE_ALLOW_SELF_SIGNED_CERTS`, **à éviter en production**).

---

## 19. Modèle de données (schéma `conges`)

| Table | Contenu |
|---|---|
| `users` | comptes : identifiant, `ad_login`, nom, e-mail, mot de passe haché, `admin`, rôle, responsable (`parent_id`), actif |
| `user_audit` | journal d'audit des comptes |
| `agents` | fiches : propriétaire, titulaire, valideur, nom, prénom, e-mail, année, `params` (JSON), `periods` (JSON), responsable d'unité |
| `cells` | demi-journées posées : (fiche, clé de demi-journée) → code |
| `settings` | paramétrage (JSON par clé : `general`, `codes`, `penibilites`, `matrix`, `jours_feries`, `vacances_scolaires`…) |
| `leave_requests` | demandes (type, code, demi-journées, jours, heures, dates, statut, valideur et responsable figés, commentaires, pièce jointe, champs d'annulation) |
| `leave_request_events` | historique des événements d'une demande |
| `hourly_absences` | absences en heures posées (fiche, date, code, horaires, heures, demande liée) |
| `api_keys` | clés API (empreinte, périmètres, IP, expiration, actif, dernier usage) |
| `api_key_logs` | journal des appels API |
| `schema_migrations` | migrations appliquées (version, somme de contrôle) |

- **DON-01** — **Migrations** SQL numérotées (`backend/migrations/`), exécutées chacune dans une transaction ; une migration déjà appliquée ne doit jamais être modifiée (somme de contrôle).
- **DON-02** — Les **dates** sont du texte `AAAA-MM-JJ[ HH:MM:SS]` (heure de Paris) pour l'instant (D3) ; fuseau de la session de base : `Europe/Paris`.
- **DON-03** — **Suppression** d'un compte : supprime ses fiches (cascade) ; l'archivage à la place est noté au backlog.
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
| Administration | `/api/v1/admin/api-keys` (+ `/logs`), `/api/admin/act-as` (+ `/search`) |
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
- À établir avec la DRH / le DPO : **registre des traitements**, **durées de conservation** (fiches, demandes, journaux d'audit, journal des appels API — sans purge aujourd'hui), minimisation des données exposées par l'API (`absences:read` révèle les codes).
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
- **DEP-05** — Un seul processus serveur : relances automatiques et limitation de débit sont en mémoire de processus.
- **DEP-06** — **Non vérifié** : les images n'ont pas encore été construites ni lancées sur un serveur Docker.
- **DEP-07** — Les sauvegardes de la base relèvent de la DSI ; le volume des pièces jointes est à sauvegarder avec.

---

## 23. Organisation du code et qualité

```
backend/    app.py (routes internes), rules.py (calcul), pg_db.py / db.py (accès PostgreSQL), config.py, apm.py, mailer.py, reminders.py,
            api_v1.py, api_keys.py, act_as.py, openapi_spec.py, ratelimit.py, http_utils.py, wsgi.py, migrations/, tests/, Dockerfile
frontend/   public/ (index.html, app.js, style.css), nginx.conf.template, nginx.dmz.conf.template, proxy_params_conges, Dockerfile
racine      docker-compose.yml, docker-compose.dmz.yml, .env.example, README.md, MANIFEST.md, CHANGELOG.md, modifications.md, CLAUDE.md
            (backend/version.py = source unique de la version)
```

- **QUA-01** — **33 tests automatiques** : régressions métier, authentification locale / AD simulée, mails (APM simulée), clés API, documentation, « se connecter en tant que » (sur un schéma PostgreSQL temporaire, créé puis supprimé) et **cohérence du versionnage** (`test_version.py`, sans base).
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
| **0.1.0** | 2026-11-10 | Première version versionnée : application du prototype DRH mise en conformité avec le guide de la Ville (sessions signées, PostgreSQL, AD et mail par l'APM, API `/api/v1`, clés API, `/api/status`, Swagger, « se connecter en tant que », Docker, frontend DMZ, organisation `backend/` / `frontend/`), manifeste et journal des versions. |
