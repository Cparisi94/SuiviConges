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

VERSION = "0.19.0"

VERSIONS = [
    {
        "version": "0.19.0",
        "date": "2026-11-17",
        "type": "minor",
        "titre": "Version mobile en DMZ (frontend dédié) et nom du valideur unifié",
        "items": [
            "Version mobile : un frontend dédié, séparé de l'application complète (dossier conges-mobile-dmz, déployé en DMZ uniquement), limité aux fonctions de base : compteurs, demandes en cours (en attente ou validées), demande simple « du … au … » (premier et dernier jour à la demi-journée) et agenda du mois. Il ne relaie que douze routes d'API ; tout le reste y est refusé.",
            "Version mobile : l'agenda écrit le type de congé (CA, RTT…) sur chaque demi-journée avec une légende des types du mois ; en demandant des jours, on répartit le total entre les types (congés annuels, RTT, CET, sujétion…) avec des boutons − et + jusqu'à ce que tous les jours soient couverts, dans la limite du solde de chaque type ; une demande est créée par type.",
            "Version mobile : on peut annuler une demande non validée (immédiat) ou demander l'annulation d'une demande validée (le valideur doit l'accepter) ; ces annulations ne concernent que ses propres demandes.",
            "Version mobile : abonnement à l'agenda du téléphone (iCalendar/ICS) — un lien personnel et secret publie en lecture seule les congés avec leur état (✅ validé, ⏳ en attente) ; aucun motif sensible n'y figure (maladie, congés familiaux… s'affichent « Absence ») ; un appui sur « iPhone », « Google Agenda » ou « Outlook » suffit pour s'abonner ; le lien se remplace ou s'arrête à tout moment.",
            "Nom du valideur unifié : partout (cartes de Mon équipe, tableau de bord, fiches, demandes, e-mails, recherche administrateur), une personne s'affiche au même format « Prénom NOM » (nom Active Directory remis dans cet ordre, à défaut son prénom et son nom de famille) ; les noms AD déjà enregistrés ont été convertis.",
        ],
    },
    {
        "version": "0.18.2",
        "date": "2026-11-17",
        "type": "patch",
        "titre": "Tableau de bord par entité, recherche rapide d'une personne (administrateur)",
        "items": [
            "Tableau de bord : les personnes sans période (fiche non créée, ou fiche à la période incomplète) sont aussi listées, avec la mention « Pas de période » à la place des soldes.",
            "Tableau de bord : les fiches sont regroupées par entité (le titre de chaque groupe est le nom de l'entité, jamais celui d'une personne) ; le valideur de l'entité vient en premier, en gras avec une étoile.",
            "Administrateur : bouton 🔍 en haut à droite (ou Ctrl+K) pour retrouver une personne par nom RH, matricule ou e-mail ; une fenêtre affiche aussitôt son valideur (et son délégataire du moment) et ses comptes : application, Active Directory, e-mail, fiches congés.",
        ],
    },
    {
        "version": "0.18.1",
        "date": "2026-11-17",
        "type": "patch",
        "titre": "Mon équipe : alerte des personnes sans lien Active Directory complet",
        "items": [
            "Mon équipe : une alerte en tête de page liste les personnes actives dont le lien Active Directory est incomplet (identifiant AD ou adresse e-mail manquant) ; leur carte porte les repères « ⚠ AD » ou « ⚠ e-mail » et le bouton « Recherche AD » pour les lier (le nom AD est alors enregistré).",
        ],
    },
    {
        "version": "0.18.0",
        "date": "2026-11-17",
        "type": "minor",
        "titre": "Nom AD affiché par défaut, API « manager d'un agent », Mon équipe et en-tête refaits",
        "items": [
            "Nom affiché : le nom de l'Active Directory est affiché par défaut (Mon équipe, en-tête, valideur de chaque carte) ; quand le nom RH (Sedit RH) est différent, il apparaît en dessous, en petit et en italique. Les noms AD sont renseignés automatiquement en arrière-plan.",
            "Nouvelle route d'API GET /api/v1/managers (droit managers:read) : on cherche un agent par nom RH, matricule ou e-mail et elle renvoie son manager (son valideur) et, s'il y en a un, son délégataire du moment ; seuls les noms RH sont cherchés et renvoyés.",
            "Mon équipe : chaque carte affiche la fin de contrat (si Sedit RH la connaît) et le solde estimé de congés et de RTT, les valideurs ont un fond plus foncé, les boutons Unité et ↑/↓ passent en haut à droite de la carte, le bouton « Voir les congés » prend toute la largeur, et l'année disparaît des cartes.",
            "Mon équipe : les personnes que vous gérez par délégation sont entourées d'un pointillé bleu et portent le badge « par délégation » ; en « Voir tout », votre propre carte n'est plus masquée.",
            "En-tête sur une seule ligne : le titre ramène à l'accueil, le nom est raccourci, la déconnexion est une icône et le Paramétrage une roue dentée ; le bouton « Mot de passe » n'est plus proposé en mode AD, même aux administrateurs.",
            "Mode AD : le mot de passe local de secours n'est plus obligatoire à la création d'un administrateur.",
            "E-mails : les boutons Valider / Refuser / Voir le calendrier s'affichent correctement dans l'ancien Outlook (boutons en cellules de tableau).",
        ],
    },
    {
        "version": "0.17.8",
        "date": "2026-11-17",
        "type": "patch",
        "titre": "Bloc « Autres » (absences Sedit RH) dans la synthèse",
        "items": [
            "Synthèse de la fiche : un bloc « Autres » indique, par type (congé maladie, garde d'enfant malade, congé de maternité/adoption/paternité, congé parental, soins à entourage familial), le nombre de jours ouvrés d'absence saisis dans Sedit RH sur l'année, à titre d'information.",
            "« Ma synthèse » affiche les mêmes totaux sous les soldes.",
        ],
    },
    {
        "version": "0.17.7",
        "date": "2026-11-17",
        "type": "patch",
        "titre": "Panneau de synthèse compact",
        "items": [
            "Synthèse de la fiche : une ligne par solde (titre et restant), le détail se déplie d'un clic sur le titre ; le panneau est moins haut et plus lisible.",
            "Le restant prévisionnel (si les demandes en attente étaient validées) n'apparaît que lorsqu'il diffère du solde actuel, dans la fiche comme dans « Ma synthèse ».",
        ],
    },
    {
        "version": "0.17.6",
        "date": "2026-11-17",
        "type": "patch",
        "titre": "Agenda Outlook à jour à chaque demande, soldes prévisionnels",
        "items": [
            "Agenda Outlook : dès qu'une demande est faite, validée, refusée ou annulée (ou qu'une fiche est modifiée), l'agenda de l'agent concerné est mis à jour en arrière-plan, sans attendre la synchronisation périodique.",
            "Agenda Outlook : un rendez-vous supprimé à la main dans Outlook est recréé à la synchronisation suivante (nécessite la nouvelle version de l'API Ville, qui sait lister les événements d'un agenda).",
            "Synthèse : à côté de chaque solde (congés annuels, RTT, sujétion, bonification, CET, total), un « restant prévisionnel » indique ce qu'il resterait si les demandes en attente étaient validées.",
        ],
    },
    {
        "version": "0.17.5",
        "date": "2026-11-17",
        "type": "patch",
        "titre": "Jours demandés provisoires dans Outlook, CET contrôlé avec Sedit RH",
        "items": [
            "Agenda Outlook : un jour (ou une demi-journée) demandé, en attente de validation, apparaît dans l'agenda en « ABSENT » avec la disponibilité « Provisoire » ; une fois la demande validée il passe en « Absent du bureau », et refusée ou annulée il disparaît.",
            "L'agenda Outlook reprend aussi les absences déjà passées de l'année en cours (et plus seulement celles à partir d'aujourd'hui).",
            "Demande de congé en CET : le contrôle du solde utilise maintenant le solde de Sedit RH quand le « Solde CET (j) » de la fiche est vide, comme la synthèse (la demande de 1 jour de CET n'était plus refusée à tort avec « Solde insuffisant : il resterait -1,0 j » malgré 60 jours).",
        ],
    },
    {
        "version": "0.17.4",
        "date": "2026-11-17",
        "type": "patch",
        "titre": "Report des périodes : seulement l'année suivante",
        "items": [
            "Mon équipe : le bouton « Reporter les périodes en … » ne propose plus que l'année qui suit l'année en cours (2027 en 2026), et seulement pour les personnes qui n'ont pas encore cette fiche ; quand une autre année est affichée (par exemple 2027), il disparaît au lieu de proposer 2028.",
        ],
    },
    {
        "version": "0.17.3",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Solde de CET en cache, agenda Outlook via l'API Ville",
        "items": [
            "Solde de CET : chaque solde lu dans Sedit RH est conservé en base (il survit aux redémarrages) ; la page le reçoit tout de suite et, s'il a plus de 10 minutes, il est recalculé en arrière-plan sans faire attendre ni échouer si Sedit RH est en panne.",
            "Solde de CET indisponible : la carte de Mon équipe en donne maintenant la raison (droit cet:read manquant, clé refusée, API Sedit RH non configurée ou à mettre à jour, Sedit RH injoignable) ; l'infobulle indique la date de lecture du solde.",
            "Agenda Outlook : l'API Ville propose maintenant les routes d'agenda utilisées par le module Exchange (création et suppression d'événements), avec une permission dédiée « Agenda O365 (événements) ».",
        ],
    },
    {
        "version": "0.17.2",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Exchange passe par l'API Ville",
        "items": [
            "Module Exchange : la synchronisation de l'agenda Outlook passe désormais par l'API Ville (api.ivry.local, clé de l'application), et non plus directement par Microsoft. Tant que l'API Ville ne propose pas la route d'agenda, la carte « Agenda Outlook » de Ma synthèse indique que la synchronisation n'est pas encore disponible.",
        ],
    },
    {
        "version": "0.17.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Ma synthèse pour tous",
        "items": [
            "Les valideurs et les administrateurs ont maintenant, eux aussi, l'entrée « Ma synthèse » dans le menu : leurs propres soldes, demandes récentes et heures, avec la carte « Agenda Outlook » ; leur « Tableau de bord » reste celui de leur équipe.",
        ],
    },
    {
        "version": "0.17.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Module exchange : absences dans l'agenda Outlook",
        "items": [
            "Nouveau module « exchange » : dans « Ma synthèse », une case permet de synchroniser automatiquement vos absences avec votre agenda Outlook (via Microsoft Graph). Chaque jour d'absence est indiqué « ABSENT » dans l'agenda, sans autre texte ; une demi-journée donne un événement sur le matin ou l'après-midi.",
            "Exchange : le télétravail (TT) apparaît dans l'agenda en « Travaille ailleurs ». Les événements suivent vos modifications de fiche (toutes les 10 minutes, ou tout de suite avec « Synchroniser maintenant ») ; décocher la case les retire de l'agenda.",
        ],
    },
    {
        "version": "0.16.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Mon équipe : valideur, unité entière, progression ; identifiants AD",
        "items": [
            "Fiche congés : l'en-tête indique le « Valideur actuel » ; quand le valideur de la fiche a délégué (absence ou période de délégation en cours), il affiche le délégataire avec la mention « par délégation de … ».",
            "Délégation automatique activée par défaut pour tous les valideurs (quand le valideur est absent une journée complète, son propre valideur est prévenu et trace ses validations) ; chacun peut la désactiver dans « Délégation ».",
            "Fiche congés : les absences saisies dans Sedit RH (CM maladie, GEM garde d'enfant malade, CT maternité-paternité-adoption, CP présence parentale, SF soins à la famille) apparaissent en couleur claire dans le calendrier, sur les jours ouvrés sans saisie, en lecture seule ; seuls le code et les dates sont repris, jamais la nature détaillée de l'arrêt.",
            "Report des périodes : si Sedit RH indique une date de fin de contrat, la période reportée s'arrête à cette date ; un contrat déjà terminé n'est pas reconduit ; une fenêtre récapitulative liste, après le report, ce qui a été reconduit (et jusqu'à quelle date), limité à la fin de contrat, non reconduit ou refusé.",
            "Solde de CET : Mon équipe affiche « CET : 60 j » sur la carte de chaque personne ; dans la fiche, le « Solde CET (j) » (solde initial du CET) vide est remplacé par le solde de Sedit RH (affiché en grisé dans le champ) : la synthèse et le tableau de bord le prennent en compte (initial − jours de CET posés). Le solde vient de l'API Sedit RH (solde initial + dépôts − retraits des comptes ouverts) ; la clé de l'API doit avoir le droit cet:read. Une valeur saisie n'est jamais remplacée.",
            "Mon équipe, définir la période : le bouton devient « Créer la période » ; une fois une période créée, le lien de la carte s'appelle « Fiche congés » (et non « Fiche 2026 ») ; le bouton « Reporter en 2027 » de chaque carte disparaît (le report se fait pour toute l'équipe avec « Reporter les périodes en 2027 »).",
            "Mon équipe : chaque carte indique le valideur de la personne (« Valideur : … »), les noms d'entités ont un fond plus pâle, et une entité créée localement porte la mention « locale ».",
            "Mon équipe : un bouton « ↓ Agent » repasse un valideur en agent ; les personnes qu'il validait remontent sous son propre valideur, et s'il était responsable d'une unité il ne l'est plus. Refusé pour un compte administrateur, pour soi-même et sans valideur.",
            "Mon équipe : en glissant un agent de « Agents Sedit RH à ajouter » sur son valideur, la liste des unités proposées se limite aux entités de la direction de ce valideur (la même liste que « ✎ Unité »).",
            "Mon équipe : quand un agent est passé valideur (bouton « ↑ Valideur » ou désigné responsable de son unité), il valide par défaut les agents de son unité qui avaient le même valideur que lui (ex. Bureau des projets) ; le nombre d'agents rattachés est annoncé.",
            "Mon équipe : un responsable d'unité qui était resté « Agent » est promu valideur à l'affichage, et le badge affiche bien « Valideur ».",
            "Mon équipe : Ctrl (ou Cmd) + clic sélectionne plusieurs personnes ; en les glissant sur leur valideur, elles sont toutes déplacées d'un coup, avec une barre de progression et la liste des refus éventuels.",
            "Mon équipe : un bouton « ↑ Valideur » sur chaque agent le passe en valideur (niveau déduit de son unité, jamais au-dessus de son propre valideur) ; l'action est journalisée.",
            "Mon équipe : le responsable d'une unité en est automatiquement le valideur ; désigner un agent responsable de son unité le passe valideur, et il valide les agents de cette unité.",
            "Mon équipe, agents Sedit RH à ajouter : une case par unité sélectionne toute l'unité d'un coup (état partiel si une partie seulement) ; on glisse ensuite la sélection sur une personne.",
            "Création de plusieurs agents : une barre de progression indique « Création 12 sur 31 : nom prénom… » ; les échecs éventuels sont comptés puis listés.",
            "Création d'une personne depuis Sedit RH : un directeur (poste « Directeur·trice … », hors adjoint et direction générale) est proposé dans sa direction (ex. BF) et non plus dans le secteur où il est affecté (ex. BF1). La même règle s'applique à la liste des agents à rapprocher dans Mon équipe.",
            "Connexion : l'identifiant Active Directory (ex. « machevalier ») est accepté à la place de l'identifiant de l'application (ex. « MCHEVALIER »), sans tenir compte de la casse ; un identifiant AD porté par plusieurs comptes est refusé.",
            "Création d'une personne : l'identifiant du compte est celui de l'Active Directory quand il est trouvé (ex. « machevalier »), et non plus « initiale du prénom + nom » (« MCHEVALIER »).",
        ],
    },
    {
        "version": "0.15.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Utilisateurs : tableau compact et suppression multiple",
        "items": [
            "Utilisateurs : le tableau est plus compact (lignes moins hautes) ; la case « Admin » devient une colonne à part ; la colonne « Mot de passe » disparaît quand la connexion se fait par l'Active Directory.",
            "Utilisateurs : sélection multiple (une case par ligne, « tout sélectionner » pour la page affichée) et bouton « Supprimer la sélection », avec une confirmation qui liste les personnes ; chaque suppression suit les mêmes règles que la suppression à l'unité (périmètre, jamais son propre compte).",
        ],
    },
    {
        "version": "0.14.4",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Tableau de bord RH réservé aux administrateurs",
        "items": [
            "Le Tableau de bord RH n'est plus accessible qu'aux comptes administrateurs : l'entrée de menu est masquée pour les valideurs et les agents, et l'accès direct par l'adresse (#/hr) ou par l'API est refusé.",
        ],
    },
    {
        "version": "0.14.3",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Mon équipe : les entités d'abord, puis leurs membres",
        "items": [
            "Mon équipe est classé par unité (entité) puis par membres : le titre de chaque entité, son responsable (★) en premier, puis les valideurs, puis les agents (ex. « Cellule administrative et financière » : Isabelle, puis Florian). Une personne est rangée dans son unité, à défaut dans celle de son valideur ; les unités de même nom sont regroupées ; déposer sur un titre place sous le responsable de l'entité.",
        ],
    },
    {
        "version": "0.14.2",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Planning : titres de groupe par entité",
        "items": [
            "Dans le planning, les titres de groupe portent le nom de l'entité (unité) et non celui du valideur : plus de doublon « Chevalier Marc » entre le groupe des encadrants et l'en-tête de son équipe.",
        ],
    },
    {
        "version": "0.14.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Planning : raison pour mon équipe, présence pour les autres, encadrants visibles",
        "items": [
            "Planning : un simple agent ne voit que la présence ou l'absence ; un encadrant voit la raison (code) pour les agents de son équipe et pour sa propre fiche ; les autres fiches n'affichent que présence / absence.",
            "Planning : un groupe « Encadrants — disponibilité » montre la disponibilité de mes encadrants (ma chaîne de valideurs) et la mienne, en présence / absence.",
        ],
    },
    {
        "version": "0.14.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Mon équipe : unité de chaque agent, unités locales et responsable d'unité",
        "items": [
            "Dans Mon équipe, le bouton « ✎ Unité » de chaque carte permet de choisir l'unité de la personne dans la liste des entités de sa direction et d'indiquer si elle en est la responsable (★).",
            "Si l'unité n'existe pas dans Sedit RH (ex. « Numérique éducatif », « Cellule administrative et financière »), on la crée localement sous l'unité choisie : elle rejoint la liste et n'est jamais écrasée par la synchronisation ; le responsable de l'unité est enregistré dans l'unité.",
            "La liste déroulante d'année du haut change aussi la fiche affichée (fiche de la même personne pour l'année choisie) ; l'année n'est plus répétée dans l'en-tête de la fiche.",
        ],
    },
    {
        "version": "0.13.2",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Barre du haut adaptée aux fenêtres étroites",
        "items": [
            "La barre du haut ne coupe plus les libellés sur plusieurs lignes quand la fenêtre n'est pas en plein écran : les menus et les boutons sont resserrés, puis le menu passe sur sa propre ligne sous le titre quand la place manque.",
        ],
    },
    {
        "version": "0.13.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "API Sedit RH : toutes les unités publiées",
        "items": [
            "L'API Sedit RH (projet api-apps/sedit-rh) publie désormais dans /api/v1/organisation les unités d'affectation portées par des agents en poste mais absentes de l'organigramme SIIM, rattachées à leur service avec le champ « origine : agents » (ex. « Équipe projet éduc. innovation inclusion », BF1112, sous la DSI) ; l'application les reprend telles quelles (sa propre complétion reste en secours).",
        ],
    },
    {
        "version": "0.13.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Années dans la fiche, report des périodes, équipes manquantes de Sedit RH",
        "items": [
            "Dans la fiche, le sélecteur d'année (à côté du nom) permet de passer à la fiche 2027 (ou d'une autre année) de la même personne, et de préparer l'année suivante : « + 2027 (reporter la période) ».",
            "On ne reproduit plus des fiches mais des périodes : le report crée la fiche de l'année suivante avec la période en vigueur en fin d'année (quotité, durée, pénibilité, jours travaillés, jours fériés travaillés) sur toute l'année ; il est refusé si la fiche de l'année existe déjà. Les boutons « Dupliquer » de Mon équipe deviennent « Reporter en 2027 » et « Reporter les périodes en 2027 ».",
            "La liste des unités reprend aussi les équipes que Sedit RH ne publie pas dans son organisation mais qui sont portées par des agents (ex. « Équipe projet éduc. innovation inclusion », code BF1112, rattachée à la DSI) : 62 unités ajoutées.",
        ],
    },
    {
        "version": "0.12.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Fiche : unité modifiable, e-mail et matricule verrouillés ; Mon équipe plus large",
        "items": [
            "Dans la fiche, l'e-mail (repris de l'annuaire) et le matricule (repris de Sedit RH) ne sont plus modifiables, côté écran comme côté serveur une fois renseignés ; l'e-mail manquant se renseigne par « Recherche AD » dans Mon équipe.",
            "La case « Resp. unité » disparaît de la fiche : le responsable d'une entité est son valideur (★ en premier dans Mon équipe).",
            "Nouveau champ « Unité » dans la fiche : on choisit l'unité de l'agent dans la liste de toutes les entités de sa direction (pour un agent de la DSI : la direction, ses services et ses secteurs) ; l'unité s'affiche aussi sur la carte dans Mon équipe quand elle diffère de celle du groupe.",
            "Mon équipe : la colonne des personnes est élargie et la liste des agents Sedit RH à ajouter est plus étroite.",
        ],
    },
    {
        "version": "0.12.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Mon équipe remplace Mes fiches : entités et périodes visuelles",
        "items": [
            "« Mes fiches » est fusionné dans « Mon équipe » : le menu « Mes fiches » disparaît (les anciens liens renvoient vers Mon équipe).",
            "Mon équipe est classé par entité (nom de l'unité Sedit RH), comme l'ancien Mes fiches : le responsable de l'entité (★) est en premier, les entités de même nom sont regroupées.",
            "Chaque personne est une carte qui montre sa période de façon visuelle : un camembert pour la quotité (100 %, 80 %…), les jours travaillés (L M M J V S D) en couleur, la durée et la pénibilité, « F » si elle travaille les jours fériés, « n périodes » s'il y en a plusieurs.",
            "On y retrouve les actions de l'ancien Mes fiches : ouvrir la fiche, « + Nouvelle fiche », « Dupliquer pour 2027 » (par personne ou pour toutes les fiches de l'équipe), et le glisser-déposer d'une carte sur une entité ou une personne pour changer son valideur.",
        ],
    },
    {
        "version": "0.11.5",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Mes congés : demandes pour tous, jamais de validation directe",
        "items": [
            "Dans « Mes congés », chacun — administrateur compris — pose des demandes sur sa propre fiche, adressées à son valideur (ou à un autre administrateur s'il n'a personne au-dessus) : plus de saisie ni de validation directe sur sa propre fiche, y compris pour les demandes d'heures et de cassage. Seuls les autres peuvent saisir directement sur sa fiche.",
        ],
    },
    {
        "version": "0.11.4",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Mon équipe : Dupliquer pour l'année suivante",
        "items": [
            "Dans « Mon équipe », à côté de « Fiche 2026 », un bouton « Dupliquer pour 2027 » (année N+1) crée la fiche de l'année suivante avec les mêmes paramètres (les congés posés ne sont pas copiés, les dates d'arrivée et de départ non plus) ; une fois créée, il est remplacé par « ✓ 2027 ».",
        ],
    },
    {
        "version": "0.11.3",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Tableau de bord RH : entités et responsables",
        "items": [
            "Le tableau de bord RH (Absences par direction / service) affiche le nom de l'entité (unité Sedit RH) et non celui de son valideur ; le responsable de l'entité apparaît en premier dans sa liste, avec la mention « (Responsable) », comme pour la DRH ; les entités de même nom (une direction et son service du même nom, deux valideurs d'une même unité) sont regroupées. Le tableau « par direction / service » reprend les mêmes noms d'entités.",
        ],
    },
    {
        "version": "0.11.2",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Fiche plus compacte ; « Mes congés » en consultation",
        "items": [
            "L'en-tête de la fiche est réduit en hauteur : une seule ligne de champs (e-mail, matricule, valideur, responsable d'unité, reliquat, solde CET) et des boutons d'heures en ligne, au lieu de trois cartes.",
            "Dans « Mes congés », les informations de la fiche ne sont plus modifiables (nom, prénom, e-mail, matricule, valideur, reliquat, solde CET) : on consulte, on pose des demandes ; pas de bouton Supprimer ni « Changer le valideur ».",
        ],
    },
    {
        "version": "0.11.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Onglets de fiches : « + » ouvre des fiches de l'équipe",
        "items": [
            "Le « + » de la barre d'onglets ne crée plus une fiche : il affiche les agents sous ma responsabilité (avec recherche) et on coche ceux dont on veut ouvrir la fiche, chacune dans son onglet. La création d'une fiche reste dans « Mes fiches ».",
        ],
    },
    {
        "version": "0.11.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "E-mails avec boutons, délégation des valideurs, Mon équipe en deux niveaux",
        "items": [
            "L'e-mail de nouvelle demande présente les dates en plages (« du 20 avril 2026 au 24 avril 2026 », week-ends sautés ; demi-journées précisées aux extrémités) au lieu d'une liste de demi-journées.",
            "L'e-mail comporte trois boutons : « Valider », « Refuser » (page de confirmation personnelle, valable 14 jours, qui n'enregistre rien tant qu'on n'a pas cliqué) et « Voir le calendrier d'équipe » (planning de mon équipe, au mois de la demande). Le texte par défaut du message est mis à jour s'il n'avait pas été personnalisé.",
            "Nouveau menu « Délégation » pour les valideurs : je délègue automatiquement à mon valideur quand je suis absent, et/ou sur des périodes du/au (même sans congés) ; mon valideur reçoit alors aussi le mail de chaque demande (avec les boutons) et les relances ; je consulte les validations faites à ma place.",
            "« Mon équipe » n'affiche plus par défaut que les personnes que je valide directement (et, le temps d'une délégation, celles de mon délégant) ; un bouton « Voir toute ma ligne hiérarchique » montre aussi celles que mes agents valident, et ainsi de suite.",
        ],
    },
    {
        "version": "0.10.2",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Planning : jours non validés en pointillé",
        "items": [
            "Dans le planning, les jours d'une demande en attente de validation s'affichent comme dans la fiche : couleur éclaircie et contour en pointillé (info-bulle « Demande en attente de validation »).",
        ],
    },
    {
        "version": "0.10.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Mes congés : sa propre fiche même pour un valideur",
        "items": [
            "Le menu « Mes congés » retrouve la fiche de congés de la personne même lorsqu'elle valide d'autres agents (sa fiche appartient à son propre valideur, donc hors de son équipe) : il affichait à tort « pas encore de fiche ».",
        ],
    },
    {
        "version": "0.10.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Mon équipe par défaut, « Voir tout » pour les administrateurs, recherche AD",
        "items": [
            "Un administrateur voit par défaut, comme tout valideur, son équipe (les personnes qu'il valide, de proche en proche) dans Mes fiches, Mon équipe, Demandes, Planning et les tableaux de bord ; un interrupteur « Voir tout » dans la barre du haut (réservé aux administrateurs, mémorisé) lui montre toute la collectivité.",
            "Les agents (hors administrateurs) ne voient ni « Mes fiches » ni « Mon équipe » : ils ont « Mes congés », « Mes demandes » et le planning.",
            "Dans Mon équipe, le bouton « Recherche AD » (sur les personnes sans e-mail) cherche leur compte dans l'Active Directory, par leur nom ou par un texte libre, et reprend l'adresse e-mail et l'identifiant AD du compte choisi ; l'adresse est relue dans l'annuaire.",
        ],
    },
    {
        "version": "0.9.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "E-mails des valideurs : compte AD retenu et alerte « sans e-mail »",
        "items": [
            "Lorsque l'annuaire contient plusieurs comptes de même nom (par exemple un compte de test sans messagerie), la création d'une personne retient désormais le seul qui a une adresse e-mail : le valideur reçoit bien ses notifications.",
            "Dans « Mon équipe », une pastille « ⚠ e-mail » signale les personnes sans adresse e-mail : aucune notification ne peut leur être envoyée.",
        ],
    },
    {
        "version": "0.9.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Menu « Mes congés » et « Mon équipe »",
        "items": [
            "Nouveau menu « Mes congés » pour tous (agent, valideur, administrateur) : on y voit sa propre fiche de congés de l'année (calendrier, soldes, demandes), sans le bloc « Paramètres et périodes » réservé au valideur ; si la fiche n'existe pas encore, un message l'explique.",
            "Le menu « Mes agents » devient « Mon équipe ». Pour un agent, « Mes fiches » (qui ne montrait que sa fiche) disparaît au profit de « Mes congés ».",
        ],
    },
    {
        "version": "0.8.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Fiches : « Valideur » et noms Prénom NOM",
        "items": [
            "Sur les fiches, « Propriétaire » devient « Valideur » (liste, fiche, tableau de bord, changement de valideur) et la personne est désignée par son prénom et son nom (exemple : Marc CHEVALIER), plus par son identifiant de connexion.",
        ],
    },
    {
        "version": "0.8.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Jours travaillés par période, entités et responsables dans « Mes fiches », noms corrigés",
        "items": [
            "Chaque période de paramètres précise les jours travaillés (cases L M M J V S D, du lundi au vendredi par défaut) et si l'agent travaille les jours fériés ; le nombre de jours par semaine suit les cases cochées.",
            "Dans le calendrier, les jours non travaillés (samedi et dimanche, jours cochés en moins, fériés non travaillés) sont grisés et non sélectionnables : une période longue ne les compte donc jamais, et le serveur refuse une demande d'absence qui les contient.",
            "La définition de la première période (Mes agents > Définir la période) comporte les mêmes cases de jours travaillés et la case « travaille les jours fériés ». Les colonnes du tableau des périodes sont resserrées pour éviter le défilement horizontal.",
            "« Mes fiches » : chaque groupe porte le nom de l'entité (unité Sedit RH) et non celui du valideur ; le responsable valideur apparaît en premier dans le groupe de son entité.",
            "Correction : le nom et le prénom sont bien séparés dans les fiches créées depuis Sedit RH (les deux fiches concernées ont été corrigées).",
        ],
    },
    {
        "version": "0.7.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Fiche congés = première période de paramètres, agents hors unité, jours hors période grisés",
        "items": [
            "Un agent glissé dans « Mes agents » est d'abord créé comme personne (compte) ; sa fiche congés n'est créée que lorsqu'on lui définit au moins une période de paramètres (pénibilité, durée, quotité, jours par semaine) : bouton « Définir la période » dans l'arbre, puis lien « Fiche 2026 ».",
            "« Mes fiches » ne liste donc que les agents sous ma responsabilité qui ont au moins une période ; la création d'une personne depuis Paramétrage > Utilisateurs suit la même règle (pas de fiche sans période).",
            "Dans « Mes agents », une case « Inclure les agents hors de mon unité (toute la collectivité) » permet de rattacher aussi des agents d'autres directions ; par défaut, seuls ceux de mon unité et en dessous sont proposés.",
            "Dans le calendrier d'une fiche, les jours qui ne sont couverts par aucune période de paramètres (avant l'arrivée, après le départ) sont grisés et non sélectionnables ; une demande d'absence sur ces jours est refusée par le serveur.",
            "Le nom de famille et le prénom sont désormais mémorisés sur le compte de la personne, pour créer sa fiche plus tard.",
        ],
    },
    {
        "version": "0.6.2",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Mes agents : sélection multiple pour le glisser-déposer",
        "items": [
            "Dans la liste des agents Sedit RH de « Mes agents », on coche plusieurs agents (ou « Tout sélectionner ») puis on les glisse en une fois sur une personne de l'arbre : ils sont tous créés sous elle, chacun dans son unité Sedit RH (ou dans une unité commune choisie). La sélection est conservée quand on lance une recherche, et le résultat indique combien d'agents ont été créés et lesquels ont échoué.",
        ],
    },
    {
        "version": "0.6.1",
        "date": "2026-11-16",
        "type": "patch",
        "titre": "Connexion : identifiant insensible à la casse",
        "items": [
            "L'identifiant de connexion n'est plus sensible aux majuscules et minuscules : « machevalier » et « MCHEVALIER » ouvrent le même compte (les comptes créés depuis Sedit RH sont en majuscules, l'identifiant de l'annuaire Active Directory est en minuscules).",
        ],
    },
    {
        "version": "0.6.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Mes agents (glisser-déposer depuis Sedit RH) et règles métier consultables",
        "items": [
            "Nouveau menu « Mes agents » : l'arbre des personnes que je valide et, de proche en proche, de celles que mes subordonnés valident.",
            "À droite, la liste des agents de Sedit RH de mon niveau ou en dessous qui ne sont pas encore dans l'application, avec recherche : on les glisse sur une personne de l'arbre pour les créer sous elle (compte, fiche, matricule, e-mail et identifiant trouvés dans l'Active Directory) ; on confirme leur unité.",
            "La personne qui reçoit un agent devient automatiquement valideur (son niveau est déduit de son unité) et, si elle n'a pas encore d'unité, prend celle de l'agent déposé : exemple, glisser Isabelle ABBAS sous Marc CHEVALIER puis Florian BRUN sous Isabelle ABBAS fait d'elle son valideur et celui de son unité.",
            "On peut aussi glisser une personne de l'arbre sur une autre pour changer son valideur (sa fiche suit) ; impossible de la placer sous elle-même ou sous un de ses subordonnés.",
            "Toutes les règles métier de l'application sont consignées dans un document (REGLES_METIER.md) lisible dans Paramétrage > Documentation > Règles métier ; il est tenu à jour à chaque version.",
            "Correction : la première ouverture simultanée de deux écrans qui chargent les unités Sedit RH ne provoque plus d'erreur.",
        ],
    },
    {
        "version": "0.5.0",
        "date": "2026-11-16",
        "type": "minor",
        "titre": "Trois rôles et unités Sedit RH : création d'une personne depuis Sedit RH et l'Active Directory",
        "items": [
            "Deux rôles : Valideur et Agent (les anciens niveaux DGS, DGA, Direction, Service, Secteur, Unité et Équipe deviennent « Valideur » ; le niveau de chacun est conservé en interne et reste déduit de son unité, donc les droits et périmètres existants ne changent pas). « Administrateur » est un droit en plus, une case à cocher : un agent ou un valideur peut être aussi administrateur (mot de passe local de secours obligatoire).",
            "Nouveau formulaire « Nouvelle personne » dans Paramétrage > Utilisateurs : on cherche la personne dans Sedit RH par saisie prédictive (nom, prénom ou matricule) ; son nom, son prénom, son matricule et son unité d'affectation sont repris automatiquement.",
            "L'adresse e-mail et l'identifiant sont ensuite cherchés dans l'Active Directory (exemple : Christophe PARISI → cparisi) : repris tels quels si le compte est unique, à choisir dans une liste s'il y en a plusieurs, à saisir à la main s'il n'y en a pas.",
            "Rôle Agent : on choisit l'unité d'affectation dans la liste des unités de l'organisation Sedit RH (direction, service, secteur, équipe) ; l'agent est rattaché automatiquement au valideur de son unité, sinon à celui de l'unité supérieure la plus proche, et sa fiche est créée.",
            "Rôle Valideur : en plus de son unité d'affectation, on choisit l'unité qui le valide (obligatoirement une unité supérieure à la sienne) ; il est rattaché au valideur de cette unité.",
            "Les unités sont copiées depuis Sedit RH à la première utilisation puis à la demande (aucune donnée personnelle) ; un valideur ne voit que les unités de son périmètre.",
            "La liste des utilisateurs affiche le rôle (trois valeurs) et l'unité de chaque personne.",
            "Un valideur de niveau Direction est validé par un DGA : le formulaire propose alors la liste des valideurs DGA/DGS (une direction n'a pas d'unité supérieure dans Sedit RH). Un DGA ou un DGS se crée avec le niveau de validation « DGA » ou « DGS », sans unité.",
        ],
    },
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
