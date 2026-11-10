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

## 0.2.1 — 2026-11-10 — E-mails : activation réglable dans l'application, tests toujours possibles, écran Messages en liste

- L'envoi automatique des e-mails s'active et se désactive dans Paramétrage > E-mails (case à cocher), et non plus dans le fichier de configuration ; il est désactivé par défaut.
- Les messages de test partent même lorsque l'envoi automatique est désactivé (dès que l'API centrale est configurée).
- Messages automatiques : la liste des messages est à gauche, un clic affiche et permet de modifier le contenu (objet, texte, activation), avec la liste des variables disponibles et leur signification.
- L'aperçu ne montre plus que le message : l'en-tête (gabarit institutionnel) et le pied de page sont ajoutés par l'API centrale de la Ville et ne sont donc pas prévisualisés ; l'en-tête propre à l'application est retiré.
- L'écran « Mise en page et expéditeur » devient « Expéditeur et pied de page » (expéditeur, signature, pied de page).

## 0.2.0 — 2026-11-10 — Paramétrage général, journaux, gabarits d'e-mails et matricule

- Le Paramétrage devient un menu général à sous-sections : Calcul et calendrier, Utilisateurs, Clés API, Journal des connexions, Mise en page et expéditeur des e-mails, Messages automatiques, Journal des e-mails.
- Journal des connexions : qui s'est connecté, quand, depuis quelle adresse IP et avec quelle méthode (local, Active Directory, secours), avec les échecs, les déconnexions et les « se connecter en tant que » ; filtres, pagination et durée de conservation réglable.
- Journal des e-mails : tous les e-mails envoyés ou tentés par l'application (destinataire, objet, résultat, texte envoyé), avec filtres et durée de conservation réglable.
- Messages automatiques : le texte et l'objet de chaque e-mail (nouvelle demande, relance des demandes en attente, message de test) se modifient dans l'application, avec des variables, un aperçu, un envoi de test et un retour au texte d'origine.
- Mise en page commune des e-mails : nom et adresse de l'expéditeur, en-tête (titre et couleur), signature et pied de page (trois lignes et couleur), avec aperçu.
- Nouveau champ Matricule sur les comptes et les fiches agents (unique), repris dans l'API et la recherche des fiches ; il servira de clé avec Sedit RH.
- Connexion par l'Active Directory : le bouton « Mot de passe » disparaît pour les agents (leur mot de passe est celui de leur compte Ville) et la création d'un compte n'exige plus de mot de passe.
- Connexion à l'API Sedit RH préparée (adresse et clé dans le fichier de configuration, état visible dans /api/status).

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
