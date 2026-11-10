# Suivi des congés — instructions de projet

Application web de suivi des congés, RTT et heures des agents de la Ville (DRH). Python/Flask + PostgreSQL (schéma `conges`),
frontend JavaScript sans framework, déploiement Docker. Référence fonctionnelle : `MANIFEST.md`. Historique : `CHANGELOG.md`.
Guide technique imposé par la DSI : `GUIDE_NOUVELLE_APP_VILLE.md`.

## Organisation
- `backend/` : API Flask (`app.py` routes internes, `rules.py` moteur de calcul, `pg_db.py`/`db.py` accès PostgreSQL, `apm.py` API centrale, `api_v1.py`,
  `api_keys.py`, `act_as.py`, `admin_settings.py` journaux et e-mails, `audit_logs.py`, `mail_templates.py`, `version.py`), `migrations/` (SQL numérotées), `tests/`, `Dockerfile`.
- `frontend/public/` : interface (HTML/CSS/JS) ; `frontend/` : nginx interne et DMZ, `Dockerfile`.
- Racine : `docker-compose.yml`, `docker-compose.dmz.yml`, `.env` (secrets, **jamais affiché ni commité**), `.env.example`, documentation.
- Ports : backend **8110**, frontend interne **8111**, frontend DMZ **8112**.

## Commandes (poste Windows, environnement virtuel à la racine)
```bash
cd backend
../.venv/Scripts/python -m unittest discover -s tests      # tests (schéma PostgreSQL temporaire, supprimé à la fin)
../.venv/Scripts/python app.py                              # serveur de développement sur http://127.0.0.1:8110
```
Docker n'est pas installé sur ce poste : les images ne peuvent pas être construites localement.

## Règles de travail
- **Aucun commit ni push sans demande explicite** de l'utilisateur. Pas d'action irréversible sans confirmation (suppression de données, schéma réel `conges`, etc.).
- Les données de la base sont des **données de démonstration** (décision D9 du manifeste).
- Ne jamais modifier une migration SQL déjà appliquée : en créer une nouvelle (numérotation continue, `backend/migrations/00NN_nom.sql`).
- Requêtes SQL **paramétrées** (`?` dans le code, traduit par `pg_db.py`) ; jamais de concaténation de saisies utilisateur.
- Texte affiché côté frontend : toujours échappé (`esc()`), jamais d'`innerHTML` avec une saisie non échappée.
- Les secrets viennent de `.env` / variables d'environnement ; ne rien mettre en dur.
- Langue : **français** (code commenté, messages, documentation).
- Les fichiers texte sont écrits en UTF-8 ; éviter les scripts de patch avec des échappements complexes dans le shell (préférer un fichier script).

## Versionnage — procédure de livraison d'une version
Convention `0.x.y` (avant la production) : **x** = ajout d'un module ou d'une fonctionnalité, **y** = correction ou amélioration sans nouveau module, `1.0.0` = production.
Version actuelle : voir `backend/version.py` (source unique).

**À chaque nouvelle version, documenter l'application avec les nouveautés** :
1. `backend/version.py` : changer `VERSION` et ajouter l'entrée **en tête** de `VERSIONS` (version, date du jour AAAA-MM-JJ, `minor` ou `patch`, titre, liste de nouveautés
   rédigée pour les utilisateurs métier).
2. `CHANGELOG.md` : ajouter la section `## X.Y.Z — AAAA-MM-JJ — titre` **en tête**, avec les mêmes nouveautés.
3. `MANIFEST.md` : mettre à jour la ligne de statut (`v X.Y.Z`), les sections fonctionnelles concernées (exigences nouvelles ou modifiées avec leurs identifiants,
   décisions de la section 0, questions ouvertes, hypothèses, écarts) et ajouter une ligne au tableau de la section 29.
4. `modifications.md` : expliquer au métier ce qui a changé, pourquoi, l'impact pour les utilisateurs et ce qui a été vérifié (ou non).
5. `README.md` si les commandes, l'architecture ou le déploiement changent.
6. Lancer les tests : `backend/tests/test_version.py` échoue si `version.py`, `CHANGELOG.md` et `MANIFEST.md` ne sont pas en phase. Vérifier aussi dans un navigateur
   (instance jetable sur un schéma temporaire) les écrans modifiés.
7. Proposer le commit à l'utilisateur (message `Version X.Y.Z : titre`) ; ne créer un tag Git `vX.Y.Z` que sur demande.

Une correction mineure sans nouveauté visible reste une version `y` : elle est quand même inscrite dans le journal.
