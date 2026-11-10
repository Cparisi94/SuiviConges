# Suivi des congés 2027

Application web multi-utilisateurs reproduisant la logique du classeur
**« Modèle Suivi congés 2027.xlsx »** (onglet AGENT) :
soldes de congés annuels, RTT, jours de sujétion, bonifications, CET,
reliquat/report, prorata d'arrivée/départ, déductions suite à absences,
et tableau de bord global.

## Démarrage

**Production / recette (Docker)** :

```bash
cp .env.example .env        # renseigner CONGES_SECRET_KEY, POSTGRES_*, APM_API_KEY…
docker-compose up -d --build
```

Ports : **backend 8110**, **frontend interne 8111**, **frontend DMZ 8112**. L'application est servie
par le frontend (nginx, `FRONT_PORT`) ; le backend (gunicorn) n'est publié que sur la machine locale
(`BACK_BIND`) tant qu'aucun frontend DMZ ne doit le joindre. Le HTTPS est assuré par le reverse-proxy
de la Ville devant les frontends. Vérification : `GET /api/status`. Documentation de l'API : `/api-docs`.

**Frontend de la DMZ** (hôte de la DMZ, sans backend ni base) :

```bash
BACKEND_URL=http://<adresse interne du backend>:8110 docker-compose -f docker-compose.dmz.yml up -d --build
```

Il relaie vers le backend interne uniquement les routes utiles aux agents ; l'API `/api/v1`, la
documentation Swagger, l'état détaillé et « se connecter en tant que » restent réservés au réseau
interne (`frontend/nginx.dmz.conf.template`).

**Poste de développement** (Python 3.12+) :

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt     # Linux : .venv/bin/pip
cd backend
../.venv/Scripts/python app.py                            # http://127.0.0.1:8110 (sert aussi le frontend)
```

Les données sont dans le PostgreSQL de la Ville, schéma `conges` (accès dans `.env` à la racine, voir
`.env.example`). Les migrations de `backend/migrations/` sont appliquées au démarrage. Au tout premier
démarrage sur un schéma vide, un compte `admin` est créé avec le mot de passe de
`CONGES_INITIAL_ADMIN_PASSWORD`, ou un mot de passe aléatoire affiché une seule fois dans la
console. `CONGES_AUTH_MODE=ad` active la connexion par l'Active Directory (via l'API centrale APM).

Version actuelle : voir `backend/version.py` (affichée dans l'application) ; journal : [CHANGELOG.md](CHANGELOG.md) ; référence fonctionnelle : [MANIFEST.md](MANIFEST.md) ; évolutions techniques expliquées au métier : [modifications.md](modifications.md).

## Rôles et hiérarchie

Quatre niveaux, avec un responsable pour chaque compte :

| Rôle | Périmètre (consultation et modification) |
|------|-----------|
| **Administrateur** | Toutes les fiches, paramétrage, gestion des utilisateurs |
| **Direction** | Toutes les fiches des services et secteurs sous sa responsabilité (+ les siennes) |
| **Service** | Toutes les fiches des secteurs sous sa responsabilité (+ les siennes) |
| **Secteur** | Uniquement ses propres fiches |

Hiérarchie : **Administrateur → Direction → Service → Secteur**.
Chaque utilisateur est rattaché à un responsable de niveau supérieur (onglet
**Utilisateurs**). Un **secteur peut aussi être rattaché directement à une
direction**, sans passer par un service.

Chaque niveau peut **modifier et supprimer les fiches de son périmètre**, y
compris celles créées par ses subordonnés (une direction peut donc modifier les
fiches des services et des secteurs rattachés). Un secteur ne voit et ne modifie
que ses propres fiches. Les tableaux de bord, la liste des fiches et le planning
sont automatiquement limités au périmètre du compte.

## Multi-année

Un **sélecteur d'année** est disponible dans la barre supérieure. Chaque fiche
appartient à une année : le tableau de bord, la liste des fiches et le planning
n'affichent que les fiches de l'année sélectionnée. Le bouton **« + »** de la
barre d'onglets crée une nouvelle fiche dans l'année sélectionnée.

Les **jours fériés** et **vacances scolaires** sont paramétrables pour plusieurs
années (2026 et 2027 sont préchargés) et s'appliquent automatiquement à l'année
de la fiche. Le calcul (prorata, droits, CA26, etc.) utilise l'année de la fiche.
L'année proposée par défaut dans le sélecteur est réglable dans
**Paramétrage > Année par défaut**.

**Duplication vers l'année suivante** : depuis la liste des fiches, le bouton
« Dupliquer en {année+1} », la sélection multiple (cases individuelles ou
« Tout sélectionner ») puis « Dupliquer la sélection », ou « Dupliquer toutes
les fiches » créent une copie dans l'année suivante. Les paramètres sont
conservés (hors dates d'arrivée/départ, propres à l'année source) et **les
congés saisis ne sont pas copiés**.

**Liste des fiches** : les fiches sont regroupées par niveau hiérarchique du
compte propriétaire (Administrateur → Direction → Service → Secteur), avec les
mêmes couleurs de brique que le planning. Un secteur rattaché directement à une
direction apparaît sous celle-ci, avant ses services.

**Planning mensuel** : avec « Toutes les fiches de mon périmètre », les fiches
sont regroupées par niveau. Les en-têtes **Direction**, **Service** et **Secteur**
utilisent des dégradés de brique du plus sombre au plus clair. Un secteur
rattaché directement à une direction apparaît sous celle-ci, avant ses services.
Les totaux par agent restent affichés dans le tableau ; la synthèse mensuelle
globale n'est plus affichée.

**Impression** : un bouton « Imprimer » est disponible sur chaque fiche et sur
le planning mensuel. La feuille de style d'impression masque la navigation, les
onglets et les boutons, conserve les couleurs (codes, week-ends, jours fériés,
vacances scolaires, niveaux hiérarchiques) et utilise le format A4 paysage. La
fiche s'imprime sur **une seule page** : les paramètres sont masqués et la
synthèse est compactée en trois colonnes sous le calendrier. Le planning
s'imprime sans la synthèse mensuelle.

Chaque fiche agent contient :
- les paramètres (pénibilité, durée, quotité, jours/semaine,
  dates d'arrivée/départ, reliquat, solde CET) ;
- un calendrier 12 mois × 2 demi-journées × 31 jours : cliquez sur une case
  ou **glissez sur plusieurs demi-journées** pour sélectionner une plage, puis
  choisissez le code à appliquer à toute la sélection (couleurs identiques au
  classeur) ;
- les **vacances scolaires de la zone C** apparaissent par un **liseré orange**
  sur le calendrier de saisie et sur le **planning mensuel** (périodes
  modifiables dans Paramétrage > Vacances scolaires) ;
- un panneau de synthèse recalculé en temps réel (droit, généré à ce jour,
  pris, déduction, restant, dépôt CET possible).

## Tests

```bash
cd backend
../.venv/Scripts/python -m unittest discover -s tests
```

Les tests utilisent un schéma PostgreSQL temporaire (créé puis supprimé) : les données réelles ne
sont jamais touchées. Ils couvrent les régressions métier, l'authentification (locale / AD simulée),
les mails (APM simulée), les clés API et le « se connecter en tant que ».

## Architecture

```
backend/                    API Flask (Python), image Docker `backend/Dockerfile`
  app.py                    Application Flask (API interne JSON ; sert le frontend en développement)
  wsgi.py                   Point d'entrée gunicorn (migrations, compte initial, tâches de fond)
  config.py                 Configuration : variables d'environnement / .env
  pg_db.py, db.py           Accès PostgreSQL (pool, schéma dédié, migrations) et helpers
  migrations/               Migrations SQL numérotées (0001_…)
  rules.py                  Moteur de calcul — formules du classeur Excel (droits, prorata, déductions…)
  apm.py                    Client unique de l'API centrale APM (AD, mail)
  mailer.py, reminders.py   Notifications aux valideurs (via l'APM) et relances
  api_v1.py                 API publique /api/v1 (lecture seule) + /api/status
  api_keys.py               Clés API (périmètres, IP, expiration, journal) + administration
  act_as.py                 « Se connecter en tant que » (administrateurs)
  admin_settings.py         Routes du Paramétrage : journaux (connexions, e-mails), réglages et gabarits des e-mails
  audit_logs.py             Écriture, consultation et purge des journaux ; mail_templates.py : gabarits et mise en page des e-mails
  sedit_rh.py               Client de l'API Sedit RH (test de connexion, effectifs, agents en poste)
  rh_import.py              Rapprochement des matricules, organisation RH et création d'agents depuis Sedit RH
  version.py                Version et journal des versions (source unique)
  openapi_spec.py           Description OpenAPI + Swagger UI (/api-docs)
  tests/                    Tests automatiques
frontend/                   Interface (HTML/CSS/JS sans dépendance) + nginx, image `frontend/Dockerfile`
  public/                   Fichiers servis aux navigateurs
  nginx.conf.template       Configuration du frontend interne (port 8111)
  nginx.dmz.conf.template   Configuration du frontend DMZ (port 8112), routes internes bloquées
docker-compose.yml          Déploiement interne (backend 8110 + frontend 8111)
docker-compose.dmz.yml      Déploiement du frontend DMZ (8112)
.env / .env.example         Configuration (à la racine, lue par docker-compose et par l'application)
```

## Écarts documentés par rapport au classeur

1. **Code « CA26 » dans le calendrier** : le classeur propose CA26 via une
   liste de validation dont les plages diffèrent par cellule (bug apparent :
   pour un reliquat de type « RP », la liste perd le code CA). Ici, la liste
   proposée est la liste S (calendrier) **+ CA26 si un reliquat reste à
   consommer**, ce qui est le comportement voulu.
2. **Année dynamique** : le classeur fige 2027 dans plusieurs formules ;
   l'application utilise l'année paramétrée (par défaut 2027). Les dates sont
   bornées au 01/01–31/12 de cette année (validation identique au classeur).
3. **Sujétions (intervalle nul)** : si la durée de cycle calculée vaut 0
   (JS total nul), aucune sujétion n'est générée (le classeur affichait #DIV/0!).
4. **Reliquat** : borne étendue à 0–100 jours (validation Excel d'origine :
   0,5–60).
5. **Durée hebdomadaire par défaut** : « 38 heures » à la création d'une fiche
   (le classeur ne prévoyait aucune valeur par défaut).
6. **Champs retirés** : « Sexe » et « Temps de travail » n'existaient pas sur
   la fiche du classeur. Le tableau « Durée → NB RTT » est une table interne
   du Paramétrage (colonnes V:W) utilisée par la matrice de droits.

## Sauvegarde

Les données sont dans PostgreSQL (sauvegarde assurée par la DSI, schéma `conges`). Les pièces
jointes des demandes sont dans le volume Docker `conges_data` (`/data/uploads`) : à sauvegarder
avec le reste.
