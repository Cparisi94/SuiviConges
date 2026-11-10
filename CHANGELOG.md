# Journal des versions — Suivi des congés (What's New)

> Convention avant la mise en production : l'application est en **0.x.y**.
> - **x** (version mineure) : ajout d'un module ou d'une fonctionnalité.
> - **y** (correctif) : correction, débogage ou amélioration sans nouveau module.
> - **1.0.0** : version de production.
> - Chaque version porte sa **date de livraison** (AAAA-MM-JJ), affichée dans le journal des versions de l'application.
>
> La version affichée par l'application est celle de `backend/version.py` (source unique). Le présent fichier, `backend/version.py` (journal affiché dans l'application)
> et `MANIFEST.md` sont tenus en phase ; un test automatique le vérifie.
>
> **Pour incrémenter** : ajouter un module ou une fonctionnalité → +1 sur x, y remis à 0 ; correction ou amélioration sans nouveau module → +1 sur y.
> Mettre à jour `backend/version.py`, ce fichier, `MANIFEST.md` (statut, sections concernées, journal), `modifications.md` et, si besoin, `README.md`.
> La procédure complète est dans `CLAUDE.md`.

## 0.1.0 — 2026-11-10 — Première version : mise en conformité avec les standards de la Ville

- Connexion sécurisée : identité par session signée (l'ancien identifiant transmis par le navigateur n'est plus accepté), limitation des essais de connexion.
- Connexion par l'Active Directory de la Ville (via l'API centrale APM), avec compte de secours pour les administrateurs ; nouveau champ « Identifiant AD » dans Utilisateurs.
- Mails de notification et relances envoyés par l'API centrale de la Ville, avec pied de page paramétrable.
- Données dans le PostgreSQL de la Ville (schéma dédié « conges »), avec migrations versionnées ; les 114 consultations de référence donnent des résultats identiques à l'ancienne base.
- « Se connecter en tant que » pour les administrateurs : recherche prédictive dans l'AD, bandeau d'identité, retour à son compte, tout est journalisé.
- API en lecture seule pour les autres applications (/api/v1) : fiches, soldes, absences, demandes ; clés API gérées dans le nouvel écran « Clés API » (périmètres, IP autorisées, expiration, journal des appels).
- État de l'application (/api/status), documentation interactive de l'API (/api-docs) et numéro de version affiché dans l'application.
- Déploiement par conteneurs Docker (backend 8110, frontend 8111) et frontend dédié à la DMZ (8112) ; dépôt organisé en backend/ et frontend/.
- Documentation : manifeste applicatif (MANIFEST.md), journal des versions (CHANGELOG.md), explications pour le métier (modifications.md).
