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

VERSION = "0.1.0"

VERSIONS = [
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
