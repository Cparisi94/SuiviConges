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

L'application est servie par le frontend (nginx) sur `FRONT_PORT` (8111 par défaut ; futur frontend DMZ : 8112) ; le backend
(gunicorn, port 8110) n'est publié que sur la machine locale tant qu'aucun frontend DMZ ne doit le joindre. Le HTTPS est assuré par le reverse-proxy de la Ville devant le frontend.
Vérification : `GET /api/status`. Documentation de l'API : `/api-docs`.

**Poste de développement** (Python 3.12+) :

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Linux : .venv/bin/pip
.venv/Scripts/python app.py                       # http://127.0.0.1:8110
```

Les données sont dans le PostgreSQL de la Ville, schéma `conges` (accès dans `.env`, voir
`.env.example`). Les migrations de `migrations/` sont appliquées au démarrage. Au tout premier
démarrage sur un schéma vide, un compte `admin` est créé avec le mot de passe de
`CONGES_INITIAL_ADMIN_PASSWORD`, ou un mot de passe aléatoire affiché une seule fois dans la
console. `CONGES_AUTH_MODE=ad` active la connexion par l'Active Directory (via l'API centrale APM).

Détail des évolutions techniques : [modifications.md](modifications.md).

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
.venv/Scripts/python -m unittest discover -s tests
```

Les tests utilisent un schéma PostgreSQL temporaire (créé puis supprimé) : les données réelles ne
sont jamais touchées. Ils couvrent les régressions métier, l'authentification (locale / AD simulée),
les mails (APM simulée), les clés API et le « se connecter en tant que ».

## Architecture

```
app.py              Application Flask (API interne JSON + service du frontend en développement)
wsgi.py             Point d'entrée gunicorn (migrations, compte initial, tâches de fond)
config.py           Configuration : variables d'environnement / .env
pg_db.py, db.py     Accès PostgreSQL (pool, schéma dédié, migrations) et helpers
migrations/         Migrations SQL numérotées (0001_…)
rules.py            Moteur de calcul — formules du classeur Excel (droits, prorata, déductions…)
apm.py              Client unique de l'API centrale APM (AD, mail)
mailer.py           Notifications aux valideurs (via l'APM)  ·  reminders.py : relances
api_v1.py           API publique /api/v1 (lecture seule) + /api/status
api_keys.py         Clés API (périmètres, IP, expiration, journal) + administration
act_as.py           « Se connecter en tant que » (administrateurs)
openapi_spec.py     Description OpenAPI + Swagger UI (/api-docs)
static/             Frontend (HTML/CSS/JS sans dépendance) — servi par nginx en Docker
docker/             Dockerfiles backend et frontend, configuration nginx
docker-compose.yml  Déploiement (backend + frontend)
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
