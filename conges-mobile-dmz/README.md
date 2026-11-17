# Suivi des congés — version mobile en DMZ

Frontend **autonome** et **minimal** pour les agents qui consultent leurs congés depuis un téléphone : page statique (HTML, CSS, JavaScript sans build)
+ nginx qui ne relaie que seize routes d'API. Projet **séparé** du reste du dépôt : build context Docker = ce dossier seul, aucune dépendance sur `frontend/`.

```
Agent ──HTTPS──▶ reverse proxy DMZ ──HTTP──▶ [conges-mobile-dmz : nginx + page] ──1 port TCP──▶ backend Suivi des congés (LAN)
```

La version mobile n'existe **qu'ici** : l'application complète (`frontend/`, ports 8111 et 8112) n'embarque aucun écran mobile.

## Fonctions (volontairement limitées)
- **Compteurs** : congés annuels, RTT, sujétion, bonification, CET, total ; solde estimé quand des jours sont en attente ;
- **Demandes en cours** : en attente de validation, ou validées à venir ;
- **Demande simple** « du … au … » (premier jour dès le matin / l'après-midi, dernier jour jusqu'à midi / au soir) : le serveur ne retient que les demi-journées travaillées, hors fériés et hors cases déjà prises ;
- **Agenda** du mois (type de congé sur chaque demi-journée, validé / en attente, jours non travaillés) ; un appui sur un jour ouvre la demande ;
- **Répartition** des jours demandés entre les types (congés annuels, RTT, CET…) avec des boutons − et + ;
- **Agenda du téléphone** : abonnement iCalendar (ICS) personnel, en lecture seule — ✅ jours validés, ⏳ jours en attente (provisoires) ; aucun motif sensible (maladie, congés familiaux… : « Absence ») ;
- **Annulation** : d'une demande non validée (immédiate), ou demande d'annulation d'une demande validée (à accepter par le valideur).

Rien d'autre : pas de validation, pas de planning, pas d'administration. Les demandes sont créées par la route habituelle `POST /api/requests` : mêmes contrôles, même circuit de validation, mêmes e-mails.

## Routes relayées (liste blanche — tout le reste : 404)
| Route | Méthode | Rôle |
|---|---|---|
| `/api/auth/login` | POST | connexion (compte de la Ville ; 5 essais par minute et par adresse) |
| `/api/auth/logout` | POST | déconnexion |
| `/api/me` | GET | session en cours |
| `/api/mobile/summary`, `/api/mobile/days` | GET | compteurs, demandes, agenda ; jours posables entre deux dates |
| `/api/requests` | POST | création d'une demande d'absence |
| `/api/mobile/calendar` | GET | état de mon abonnement à l'agenda du téléphone |
| `/api/mobile/calendar/link`, `/api/mobile/calendar/revoke` | POST | créer (ou remplacer) mon lien d'abonnement ; l'arrêter |
| `/cal/<jeton>.ics` | GET | flux iCalendar lu par le téléphone, **sans session** (le jeton secret fait foi) |
| `/api/activation/start`, `/sms`, `/otp`, `/email`, `/password`, `/forgot`, `/reset` | POST | agents sans compte AD : première connexion (matricule + code d'activation, SMS de contrôle du smartphone, e-mail facultatif, mot de passe) et mot de passe oublié par SMS (sans session ; 12 requêtes par minute et par adresse) |
| `/api/mobile/requests/<id>/cancel`, `/api/mobile/requests/<id>/cancel-request` | POST | annulation d'une demande en attente ; demande d'annulation d'une demande validée (réservées à mes demandes) |

`/api/status` répond `ok` sans interroger le backend ; `/api/diag` relaie réellement la sonde du backend (`200` = joignable, `502`/`504` = pare-feu, `MOBILE_BACKEND_HOST` ou `MOBILE_BACKEND_PORT`).
L'en-tête `X-Scope` (vue « Voir tout » de l'application complète) est effacé à chaque relais.

## Paramètres (variables d'environnement)
Copier `.env.example` en `.env` (non versionné) sur l'hôte Docker de la DMZ :

| Variable | Rôle | Défaut |
|---|---|---|
| `MOBILE_BACKEND_HOST` | adresse du backend sur le LAN (obligatoire) | — |
| `MOBILE_BACKEND_PORT` | port du backend : la seule ouverture du pare-feu DMZ → LAN | 8110 |
| `MOBILE_DMZ_PORT` | port publié du conteneur | 8113 |

**Recommandé** : faire pointer `MOBILE_BACKEND_HOST` / `MOBILE_BACKEND_PORT` vers le **backend mobile** (`backend-mobile`, port 8115 du `docker-compose.yml` principal) plutôt que vers le backend complet : même si le nginx était mal réglé, ce backend ne répond de toute façon qu'aux routes de la version mobile (`backend/mobile_mode.py`). La même page est aussi servie par ce backend sous `/mobile/` du frontend interne : elle fonctionne à la racine d'un nginx comme sous un préfixe (adresses relatives).

Côté backend : `CONGES_PROXY_HOPS` doit compter ce nginx (et le reverse-proxy de la Ville devant lui) pour que l'adresse du client soit celle vue par le journal des connexions.

## Construire et lancer
```
docker compose up -d --build
```
Conteneur en lecture seule, `no-new-privileges`, aucun volume.

## Développement (poste sans Docker)
```
cd conges-mobile-dmz
../.venv/Scripts/python dev_server.py                 # http://127.0.0.1:8113, backend http://127.0.0.1:8110
../.venv/Scripts/python dev_server.py 8113 http://127.0.0.1:8110
```
`dev_server.py` joue le rôle de nginx (mêmes routes autorisées, même 404 pour le reste) ; il ne sert qu'au développement. Le backend se lance comme d'habitude
(`cd backend && ../.venv/Scripts/python app.py`). La page est faite pour un téléphone : réduire la fenêtre du navigateur (≈ 390 px) pour la contrôler.

## Ce que la DMZ ne contient pas
Aucune base de données, aucun secret, aucune clé d'API, aucun code de l'application complète. Le seul lien avec le LAN est le port du backend.
