# -*- coding: utf-8 -*-
"""Version de l'application et journal des versions (« Nouveautés »).

Convention (avant la production) : l'application est en 0.x.y.
  - x (mineure) : ajout d'un module ou d'une fonctionnalité ;
  - y (correctif) : correction, débogage ou amélioration sans nouveau module ;
  - 1.0.0 : version de production ;
  - date : jour de livraison (AAAA-MM-JJ), à renseigner pour chaque version.

Ce fichier est la SOURCE UNIQUE de la version : elle est affichée dans l'application, renvoyée par
`/api/version` et `/api/status`, et reprise dans la spécification Swagger. Il est tenu en phase avec
`CHANGELOG.md` et `MANIFEST.md` (un test le vérifie). Procédure de livraison : voir `CLAUDE.md`.
Les nouvelles versions s'ajoutent EN TÊTE de VERSIONS.
"""

VERSION = "0.4.0"

VERSIONS = [
    {
        "version": "0.4.0",
        "date": "2026-11-10",
        "type": "minor",
        "titre": "Organisation Sedit RH, matricules et création d'agents depuis la base RH",
        "items": [
            "Nouvel écran Paramétrage > Intégrations > Matricules : retrouve dans Sedit RH, par nom et prénom, le matricule des agents déjà présents dans l'application ; seules les correspondances certaines sont proposées, on coche ce qu'on applique (les homonymes et les introuvables sont signalés, jamais modifiés).",
            "Matricules appliqués à la base : 30 agents sur 34 (les 4 autres sont introuvables dans Sedit RH et restent à saisir à la main dans Utilisateurs).",
            "Nouvel écran Paramétrage > Intégrations > Organisation RH : l'organisation de Sedit RH sous forme d'arborescence Direction › Service › Secteur › Agent, comme la hiérarchie de l'application, avec le nombre d'agents, ceux déjà présents dans l'application, le compte valideur correspondant à chaque unité, une recherche et un filtre.",
            "Création d'agents depuis l'organisation RH : on coche un agent, un secteur, un service ou une direction entière (seuls les agents absents sont cochables), puis « Créer les agents sélectionnés » : aperçu complet avant toute création (rien n'est écrit), puis création des comptes et des fiches avec le matricule repris de Sedit RH.",
            "Les comptes valideurs manquants de l'organisation (direction, service, secteur) peuvent être créés automatiquement, sous le compte du même nom s'il existe ; les agents sont rattachés au compte de leur unité, ou à un propriétaire par défaut choisi.",
            "L'e-mail et l'identifiant de connexion sont cherchés dans l'annuaire Active Directory quand le nom correspond à un seul compte ; sinon ils restent à renseigner. La date d'arrivée issue de Sedit RH n'est reprise que si elle tombe dans l'année de la fiche.",
            "Les données de Sedit RH ne sont lues qu'à la demande de l'administrateur et conservées quelques minutes en mémoire : seuls les agents que l'on choisit de créer ou de rapprocher sont enregistrés.",
        ],
    },
    {
        "version": "0.3.0",
        "date": "2026-11-10",
        "type": "minor",
        "titre": "Test de l'API Sedit RH et nombre d'agents",
        "items": [
            "Nouveau menu Paramétrage > Intégrations > API Sedit RH : affiche la configuration (adresse, clé renseignée ou non — la clé n'est jamais affichée) et un bouton pour tester la connexion.",
            "Le test interroge l'API Sedit RH et indique si la connexion réussit (durée de réponse comprise), le nombre d'agents en poste et leur répartition par statut ; en cas d'échec, la cause est expliquée (API non configurée, injoignable, clé refusée, droit manquant).",
            "Le nombre d'agents est lu dans les effectifs agrégés de Sedit RH : aucune donnée personnelle d'agent n'est lue ni enregistrée.",
            "Correction d'affichage : les boutons principaux (orange) ne deviennent plus illisibles lorsque la souris les survole.",
        ],
    },
    {
        "version": "0.2.3",
        "date": "2026-11-10",
        "type": "patch",
        "titre": "E-mails : adresse du test d'envoi saisissable à côté du bouton",
        "items": [
            "Messages automatiques : l'adresse du test d'envoi se saisit dans un champ à côté du bouton « Envoyer le test » (elle est mémorisée dans le navigateur), au lieu de réclamer une adresse e-mail sur le compte sans dire où la saisir.",
        ],
    },
    {
        "version": "0.2.2",
        "date": "2026-11-10",
        "type": "patch",
        "titre": "Déploiement Docker : sous-réseau fixe configurable",
        "items": [
            "Le déploiement Docker déclare un sous-réseau fixe et configurable (variables CONGES_SUBNET et CONGES_DMZ_SUBNET) : il ne dépend plus des plages d'adresses automatiques du serveur, qui peuvent être épuisées sur un serveur Docker très utilisé.",
        ],
    },
    {
        "version": "0.2.1",
        "date": "2026-11-10",
        "type": "patch",
        "titre": "E-mails : activation réglable dans l'application, tests toujours possibles, écran Messages en liste",
        "items": [
            "L'envoi automatique des e-mails s'active et se désactive dans Paramétrage > E-mails (case à cocher), et non plus dans le fichier de configuration ; il est désactivé par défaut.",
            "Les messages de test partent même lorsque l'envoi automatique est désactivé (dès que l'API centrale est configurée).",
            "Messages automatiques : la liste des messages est à gauche, un clic affiche et permet de modifier le contenu (objet, texte, activation), avec la liste des variables disponibles et leur signification.",
            "L'aperçu ne montre plus que le message : l'en-tête (gabarit institutionnel) et le pied de page sont ajoutés par l'API centrale de la Ville et ne sont donc pas prévisualisés ; l'en-tête propre à l'application est retiré.",
            "L'écran « Mise en page et expéditeur » devient « Expéditeur et pied de page » (expéditeur, signature, pied de page).",
        ],
    },
    {
        "version": "0.2.0",
        "date": "2026-11-10",
        "type": "minor",
        "titre": "Paramétrage général, journaux, gabarits d'e-mails et matricule",
        "items": [
            "Le Paramétrage devient un menu général à sous-sections : Calcul et calendrier, Utilisateurs, Clés API, Journal des connexions, Mise en page et expéditeur des e-mails, Messages automatiques, Journal des e-mails.",
            "Journal des connexions : qui s'est connecté, quand, depuis quelle adresse IP et avec quelle méthode (local, Active Directory, secours), avec les échecs, les déconnexions et les « se connecter en tant que » ; filtres, pagination et durée de conservation réglable.",
            "Journal des e-mails : tous les e-mails envoyés ou tentés par l'application (destinataire, objet, résultat, texte envoyé), avec filtres et durée de conservation réglable.",
            "Messages automatiques : le texte et l'objet de chaque e-mail (nouvelle demande, relance des demandes en attente, message de test) se modifient dans l'application, avec des variables, un aperçu, un envoi de test et un retour au texte d'origine.",
            "Mise en page commune des e-mails : nom et adresse de l'expéditeur, en-tête (titre et couleur), signature et pied de page (trois lignes et couleur), avec aperçu.",
            "Nouveau champ Matricule sur les comptes et les fiches agents (unique), repris dans l'API et la recherche des fiches ; il servira de clé avec Sedit RH.",
            "Connexion par l'Active Directory : le bouton « Mot de passe » disparaît pour les agents (leur mot de passe est celui de leur compte Ville) et la création d'un compte n'exige plus de mot de passe.",
            "Connexion à l'API Sedit RH préparée (adresse et clé dans le fichier de configuration, état visible dans /api/status).",
        ],
    },
    {
        "version": "0.1.0",
        "date": "2026-11-10",
        "type": "minor",
        "titre": "Première version : mise en conformité avec les standards de la Ville",
        "items": [
            "Connexion sécurisée : identité par session signée (l'ancien identifiant transmis par le navigateur n'est plus accepté), limitation des essais de connexion.",
            "Connexion par l'Active Directory de la Ville (via l'API centrale APM), avec compte de secours pour les administrateurs ; nouveau champ « Identifiant AD » dans Utilisateurs.",
            "Mails de notification et relances envoyés par l'API centrale de la Ville, avec pied de page paramétrable.",
            "Données dans le PostgreSQL de la Ville (schéma dédié « conges »), avec migrations versionnées ; les 114 consultations de référence donnent des résultats identiques à l'ancienne base.",
            "« Se connecter en tant que » pour les administrateurs : recherche prédictive dans l'AD, bandeau d'identité, retour à son compte, tout est journalisé.",
            "API en lecture seule pour les autres applications (/api/v1) : fiches, soldes, absences, demandes ; clés API gérées dans le nouvel écran « Clés API » (périmètres, IP autorisées, expiration, journal des appels).",
            "État de l'application (/api/status), documentation interactive de l'API (/api-docs) et numéro de version affiché dans l'application.",
            "Déploiement par conteneurs Docker (backend 8110, frontend 8111) et frontend dédié à la DMZ (8112) ; dépôt organisé en backend/ et frontend/.",
            "Documentation : manifeste applicatif (MANIFEST.md), journal des versions (CHANGELOG.md), explications pour le métier (modifications.md).",
        ],
    },
]


def current():
    """Entrée du journal correspondant à la version courante."""
    return VERSIONS[0]
