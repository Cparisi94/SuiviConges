# Règles métier — Suivi des congés

> Ce document consigne **l'ensemble des règles métier** de l'application. Il est lisible dans l'application (Paramétrage > Documentation > Règles métier).
> **Toute règle ajoutée ou modifiée doit y être inscrite dans la même version** (procédure dans `CLAUDE.md`). Le détail technique et fonctionnel complet est dans `MANIFEST.md`.
> Dernière mise à jour : version 0.19.0.

## 1. Rôles, hiérarchie et périmètre

- **Deux rôles** : **Valideur** et **Agent**. **Administrateur** est un **droit supplémentaire** (case à cocher) qu'un agent ou un valideur peut cumuler ; un administrateur a tous les droits.
- Une personne qui **valide d'autres personnes est valideur** ; une personne qui n'en valide aucune est agent. Glisser un agent sous un autre le transforme automatiquement en valideur (voir section 2).
- En interne, un niveau (DGS, DGA, direction, service, secteur, unité, équipe) est déduit de l'**unité organisationnelle** de la personne ; il sert au calcul des périmètres et à l'affichage hiérarchique : `Administrateur > DGS > DGA > Direction > Service > Secteur > Unité > Équipe > Agent`.
- **Périmètre** : un valideur voit et gère **les personnes qu'il valide et, de proche en proche, celles que ses subordonnés valident** (fiches, planning, demandes, tableaux de bord). **Un administrateur voit lui aussi son équipe par défaut** ; l'interrupteur **« Voir tout »** de la barre du haut lui montre toute la collectivité. Un agent ne voit que sa fiche (et le planning de son équipe, motifs masqués).
- Un utilisateur ne peut pas être son propre responsable ; un agent doit être rattaché à un valideur ; un niveau intermédiaire peut être sauté.
- À la suppression d'un compte, ses subordonnés **remontent** au premier ancêtre valide.
- **Valideur et responsable d'unité** : un valideur peut passer un agent de son équipe en valideur (niveau déduit de son unité, jamais au-dessus de son propre valideur ; journalisé). **Le responsable d'une unité en est automatiquement le valideur** : le désigner responsable passe un agent valideur, et il valide les agents de son unité (avant les autres valideurs de cette unité). Un agent promu valideur **valide par défaut les agents de son unité** qui avaient le même valideur que lui. Dans Mon équipe, on peut sélectionner plusieurs personnes (Ctrl + clic) et les déplacer ensemble sous un valideur ; chaque déplacement suit les règles du déplacement à l'unité. Un valideur peut être **repassé agent** : les personnes qu'il valide remontent sous son propre valideur et il n'est plus responsable d'unité (impossible pour un administrateur, pour soi-même, ou sans valideur). Le **solde de CET** (jours) est lu dans Sedit RH (solde initial + dépôts − retraits) et affiché pour chaque personne de l'équipe ; dans la fiche, **un solde initial de CET non saisi est remplacé par celui de Sedit RH** (une valeur saisie prime). **Report des périodes** : la période reportée sur l'année suivante s'arrête à la **date de fin de contrat** de Sedit RH quand il y en a une ; un contrat terminé avant l'année n'est pas reconduit ; un récapitulatif est affiché. Le report n'est proposé que **vers l'année qui suit l'année en cours**, pour les personnes qui n'ont pas encore la fiche de cette année-là. Le **valideur actuel** d'une fiche est le délégataire quand son valideur a délégué (« par délégation de … »). La **délégation automatique est activée par défaut** pour tous les valideurs. Les **absences saisies dans Sedit RH** (CM, GEM, CT, CP, SF) sont affichées en lecture seule dans le calendrier de la fiche, sans détail médical. Quand on rattache un agent de Sedit RH sous un valideur, seules les **entités de la direction de ce valideur** sont proposées comme unité.
- **Suppression multiple** : les comptes cochés sont supprimés un par un avec les mêmes règles que la suppression à l'unité (périmètre du valideur, jamais son propre compte) ; les refus sont signalés.
- Un **valideur de niveau Direction est validé par un DGA** (ou un DGS) ; un DGA par un DGS ; le valideur supérieur est toujours d'un niveau plus élevé.
- Les contrôles sont faits **côté serveur** ; l'interface masque seulement ce qui n'est pas permis.

### Droits

| Action | Agent | Valideur (périmètre) | Administrateur |
|---|:-:|:-:|:-:|
| Voir une fiche | la sienne | celles du périmètre | toutes |
| Créer une fiche / une personne | non | oui | oui |
| Saisir directement des absences | non (même la sienne) | oui (jamais sur sa propre fiche) | oui (jamais sur sa propre fiche) |
| Demander une absence en jours | pour sa fiche | non (il saisit directement) | oui |
| Valider / refuser une demande | non | si assigné ou supérieur hiérarchique de l'assigné (jamais un subordonné) | toutes |
| Créer des administrateurs, clés API, « en tant que », paramétrage | non | non | oui |

## 2. Création des personnes et rattachement

- Une personne se crée **depuis Sedit RH** (recherche prédictive par nom, prénom ou matricule) : nom, prénom, matricule et unité d'affectation sont repris (un **directeur** — poste « Directeur·trice … », hors adjoint et direction générale — est rattaché à sa **direction**, par exemple BF, et non au secteur où il est affecté, par exemple BF1) ; l'**e-mail et l'identifiant** sont cherchés dans l'**Active Directory** (identifiant attendu : initiale du prénom + nom, ex. `cparisi`) et **devient l'identifiant du compte** ; s'il y a plusieurs comptes, on choisit ; s'il n'y en a aucun, on saisit.
- Si l'annuaire n'a pas été trouvé à la création, le bouton **« Recherche AD »** de Mon équipe cherche le compte (par le nom ou un texte libre) et reprend son e-mail et son identifiant.
- Le **matricule** est unique ; l'**identifiant AD** n'est utilisé que par un compte.
- **Agent** : unité d'affectation obligatoire ; il est rattaché au valideur de son unité, sinon à celui de l'unité supérieure la plus proche ; son **compte** est créé (identifiant = celui de l'**Active Directory** quand il est connu, ex. `machevalier` ; à défaut initiale du prénom + nom ; suffixe numérique si doublon, casse ignorée). Sa **fiche congés** n'est créée que lorsqu'on lui définit au moins une **période de paramètres** (voir section 3).
- **Valideur** : unité d'affectation et **unité qui le valide** (forcément supérieure à la sienne, jamais de cycle). Une direction n'a pas d'unité supérieure : elle est validée par un **DGA** choisi dans la liste des valideurs DGA/DGS. Un DGA ou un DGS se crée sans unité.
- **Administrateur en plus** : mot de passe local de secours obligatoire ; réservé aux administrateurs.
- Un valideur ne crée que dans son périmètre ; chaque création est inscrite au **journal d'audit** des comptes.
- Les **unités** (direction › service › secteur › équipe) viennent de Sedit RH, complétées par les équipes que des agents portent sans qu'elles figurent dans l'organisation publiée ; elles sont recopiées à la première utilisation puis à la demande (aucune donnée personnelle).

### Menu « Mon équipe » (glisser-déposer)

- L'écran **Mon équipe** affiche, en arbre, **les personnes que je valide directement** (et, le temps d'une délégation, celles de mon délégant) ; le bouton **« Voir toute ma ligne hiérarchique »** montre aussi **celles que mes subordonnés valident**, et ainsi de suite.
- À droite, la liste des **agents de Sedit RH de mon niveau ou en dessous** (unité du valideur et unités descendantes ; tous pour un administrateur) qui ne sont **pas encore dans l'application**.
- **Glisser un agent de Sedit RH sur une personne de l'arbre** (ou sur moi-même) le crée dans l'application **sous cette personne** : compte (valideur = cette personne), matricule, e-mail et identifiant AD trouvés dans l'AD s'ils sont uniques. On confirme son **unité** (proposée d'après Sedit RH). La fiche congés se crée ensuite avec **« Définir la période »**.
- Par défaut, seuls les agents de **mon unité et en dessous** sont proposés ; la case **« Inclure les agents hors de mon unité »** propose toute la collectivité (ils sont rattachés sous une personne de mon périmètre).
- La personne sous laquelle on dépose **devient valideur** (si elle était agent) ; son niveau interne est celui de son unité, sans jamais dépasser celui de son propre valideur. Si elle n'a pas encore d'unité, elle prend l'unité de la personne déposée : elle valide ainsi l'agent **et son unité**.
- Chaque personne de Mon équipe qui a une fiche peut être **dupliquée pour l'année suivante** (bouton « Dupliquer pour N+1 ») : paramètres conservés, congés et dates d'arrivée / de départ non copiés.
- On peut **cocher plusieurs agents** (ou tout sélectionner) et les glisser **en une fois** : chacun est créé sous la personne, dans son unité Sedit RH ou dans une unité commune choisie.
- On peut aussi **déplacer** une personne déjà présente d'un valideur à un autre (glisser dans l'arbre) ; sa fiche change de propriétaire et de valideur. On ne peut pas déplacer une personne sous elle-même ou sous un de ses subordonnés.

## 3. Fiche agent

- **Une fiche congés n'existe que si la personne a au moins une période de paramètres** (pénibilité, durée, quotité, jours par semaine). La personne est d'abord créée (compte), puis on lui **définit sa première période** (Mon équipe > « Définir la période ») ; la période démarre à la date d'arrivée de Sedit RH si elle tombe dans l'année, sinon au 1er janvier, et va jusqu'au 31 décembre. **Mon équipe** montre donc, pour chaque agent sous ma responsabilité, sa période (quotité, jours travaillés) dès qu'il en a une.

- Identité : nom et prénom en majuscules, e-mail valide, matricule facultatif et unique.
- Rattachement : **valideur** de la fiche (anciennement « propriétaire », un valideur actif, affiché par son prénom et son nom), **valideur** de la fiche, année, indicateur « responsable d'unité » (un seul par propriétaire et par année).
- Paramètres de calcul : pénibilité, durée hebdomadaire (35 h à 38 h), quotité (100 % à 50 %), jours travaillés par semaine (5 à 1), date d'arrivée, date de départ, reliquat, solde CET. Plusieurs **périodes** de paramètres sont possibles dans l'année.
- **Multi-année** : sélecteur d'année ; jours fériés et vacances paramétrables par année. La **duplication vers l'année suivante** garde les paramètres sauf les dates d'arrivée et de départ ; les congés saisis ne sont pas copiés.
- Impression d'une fiche sur une page A4 paysage.
- **Années** : le sélecteur d'année de la fiche passe à l'année d'une même personne. On ne reproduit pas des fiches mais des **périodes** : « reporter la période » crée la fiche de l'année suivante avec la période en vigueur en fin d'année (quotité, jours travaillés, fériés) sur toute l'année suivante ; les congés posés, les dates d'arrivée et de départ ne sont pas reportés ; un report est refusé si la fiche de l'année existe déjà.
- **E-mail et matricule ne se modifient pas dans la fiche** (ils viennent de l'annuaire et de Sedit RH ; un e-mail manquant se renseigne par la « Recherche AD » de Mon équipe). Le **responsable d'une entité** est son valideur (il n'y a plus de case « Responsable d'unité »).
- **Unités locales et responsable d'unité** : une unité absente de Sedit RH (« Numérique éducatif », « Cellule administrative et financière »…) se crée localement sous une unité existante ; elle n'est jamais écrasée par la synchronisation. On désigne le **responsable** d'une unité (une personne ne dirige qu'une unité) depuis le bouton « ✎ Unité » de Mon équipe.
- **Unité d'une personne** : modifiable depuis la fiche, parmi **toutes les unités de sa direction** (direction, services, secteurs, équipes).
- Le **« + » de la barre d'onglets** propose les agents sous ma responsabilité : on coche ceux dont on veut ouvrir la fiche (un onglet par fiche).
- **Mon équipe** (qui remplace « Mes fiches ») regroupe les personnes et leurs fiches par **entité** (nom de l'unité Sedit RH du responsable) ; le **responsable valideur** de l'entité apparaît en premier dans son groupe.

## 4. Calendrier et codes d'absence

- **Sur sa propre fiche, tout le monde fait des demandes** (jours, heures, cassage), **administrateur compris** : elles vont à son valideur (à défaut un autre administrateur) ; il n'y a jamais de saisie ni de validation directe de ses propres congés.
- **Mes congés** : chacun (agent, valideur, administrateur) consulte sa propre fiche de congés de l'année **sans pouvoir en modifier les informations** (nom, e-mail, matricule, valideur, reliquat, solde CET) : il y pose des demandes ; les paramètres et périodes de sa fiche ne s'y affichent pas, ils sont définis par son valideur (Mon équipe).

- Grille de 12 mois × 31 jours × 2 demi-journées ; une demi-journée ne porte qu'un code ; dates bornées à l'année de la fiche.
- La saisie directe est réservée aux valideurs et à l'administrateur ; l'agent passe par une demande.
- Chaque période définit les **jours travaillés** de l'agent (cases L M M J V S D, du lundi au vendredi par défaut ; leur nombre est le nombre de jours par semaine) et s'il **travaille les jours fériés** (non par défaut).
- Les **jours non travaillés** et les **jours couverts par aucune période** (avant l'arrivée, après le départ…) sont **grisés, non sélectionnables et non décomptés** quand l'agent pose une période longue ; une demande d'absence qui les contient est refusée.
- Les absences en heures (CAH, RTTH, RCH) occupent les demi-journées correspondantes : aucune absence en jours ne peut être posée au même endroit.
- **Codes demandables par l'agent** : CA, CA n-1 (s'il reste du reliquat), RTT, JB, JS, MD, AS, CET.
- **Codes comptés dans le taux d'absence** : AI, AS, CA, CA n-1, CAH, CET, CM, CP, CT, ET, GEM, GR, JB, JS, MD, RTT, RTTH, SF, SX, TP, RCH. Le télétravail (TT) n'est pas une absence.

## 5. Moteur de calcul

- **Droits annuels** lus dans la matrice (pénibilité × durée × quotité × jours hebdomadaires) : CA, RTT, sujétions (JS), bonifications (JB), droit CET.
- **Prorata** d'arrivée et de départ sur le nombre de jours calendaires de présence.
- **Sujétions** générées à des dates calculées selon un intervalle de cycle (aucune si l'intervalle est nul) ; **bonifications** selon les formules du classeur d'origine.
- **Reliquat** intégré au solde dès la saisie, consommé par le code CA n-1.
- **Déductions** : maladie, grève, exclusion… réduisent certains droits (RTT, JS…). Elles se calculent à partir des absences de **Sedit RH** (CM, CP, CT : règle inchangée), relues à chaque affichage d'un planning ou d'un compteur et conservées en base (dernière lecture si Sedit RH est indisponible).
- **Absences de Sedit RH** (CM, CP, CT, GEM, SF, ASA) : elles ne comptent que sur les **jours travaillés** de la personne (ni week-end, ni jour férié non travaillé, ni hors période). **Sedit RH fait foi** : ses absences écrasent et annulent les absences saisies dans l'outil sur les mêmes demi-journées. Ces codes **ne sont pas saisissables** dans l'outil (palette de saisie et serveur).
- **Menu Utilisateurs** : réservé aux administrateurs.
- **Soldes** = droits − pris, par type et au total ; certains droits s'acquièrent au fil de l'année (« généré à ce jour »).
- **Cassage** : seuls le CA de l'année (jamais le reliquat) et les RTT déjà générés peuvent être cassés en heures.
- Les arrondis reproduisent ceux d'Excel.

## 6. Demandes et validation

- Types : **absence** (jours), **cassage**, **heures** (CAH / RTTH), **récupération** (RCH).
- Contrôles à la demande : code autorisé, jours valides dans l'année, pas de chevauchement (absence, demande en attente, heures), **solde suffisant**, reliquat CA n-1 disponible. Pièce jointe facultative (5 Mo maximum).
- Le **validateur** d'une demande est le valideur de la fiche, à défaut le responsable N+1 actif en remontant, à défaut un administrateur. **Validation automatique** sans valideur au-dessus, ou quand un responsable saisit lui-même un cassage / des heures / une récupération pour un agent de son périmètre.
- Les noms du valideur et du responsable d'unité sont **figés** dans la demande.
- **États** : en attente → validée / refusée ; en attente → annulée (par l'auteur, le titulaire ou l'administrateur) ; validée → annulation demandée → annulée ou de nouveau validée.
- Valider : seulement si « en attente », par l'assigné ou un supérieur hiérarchique (jamais un subordonné) ; les contrôles sont refaits à la validation (conflit → erreur 409).
- On ne peut pas annuler une demande dont des heures ont déjà été consommées.
- Chaque étape est tracée dans l'historique de la demande.

## 6 bis. Délégation des valideurs

- Un valideur peut **déléguer à son propre valideur** (son responsable direct) : **automatiquement quand il est absent** (journée complète posée dans sa fiche) et/ou **sur des périodes du/au**, même sans congés.
- Pendant une délégation, le délégataire reçoit **aussi** le mail de chaque nouvelle demande (avec les boutons) et les relances ; il pouvait déjà valider (un supérieur valide les demandes de ses subordonnés) : la délégation le prévient et **garde la trace** de ses décisions.
- Le valideur consulte les **validations faites à sa place** (qui, quand, quelle décision).

## 7. Heures

- **Une journée = 7 heures.**
- Les compteurs CAH et RTTH sont crédités par les cassages **validés** ; un cassage en attente réserve le jour sans créditer d'heures.
- **RCH** : valables **6 mois** à partir de la date de réalisation, consommées dans l'ordre d'ancienneté ; les heures expirées ne sont plus utilisables ; alerte à 30 jours de l'expiration.
- Un valideur peut modifier ou supprimer des heures posées sur sa fiche, jamais l'agent.

## 8. Tableaux de bord et planning

- La **version mobile** (frontend dédié, accessible en DMZ uniquement) est limitée à la **propre fiche** de la personne : compteurs, demandes en cours (en attente ou validées à venir), demande simple « du … au … » et agenda. Les jours demandés se répartissent entre les types de congés (congés annuels, RTT, CET…) dans la limite du solde de chaque type ; une demande est créée par type. Une demande **non validée** peut être annulée tout de suite ; pour une demande **validée**, on demande l'annulation, que le valideur doit accepter (jours posés tant qu'il ne l'a pas fait) ; depuis le mobile, seules ses propres demandes sont concernées. **Absences Sedit RH** : l'agenda mobile affiche aussi, en lecture seule et en couleur claire, les absences de la personne saisies dans Sedit RH (jours travaillés seulement) ; elles n'entrent dans aucun solde. **Agenda du téléphone** : l'agent peut s'abonner (lien personnel et secret, lecture seule) pour voir ses congés dans l'agenda de son téléphone, ✅ validés ou ⏳ en attente ; aucun motif sensible n'y figure (maladie, congés familiaux, absences particulières : « Absence ») ; le lien se remplace ou s'arrête à tout moment. La demande suit les mêmes contrôles et le même circuit de validation que dans l'application complète ; seules les demi-journées travaillées (hors fériés et hors cases déjà prises) sont posées.
- Le **tableau de bord** regroupe les fiches **par entité** (unité Sedit RH de la personne) ; le titre de chaque groupe est le nom de l'entité. Le **valideur de l'entité** (son responsable désigné, sinon le valideur de plus haut niveau rattaché à l'unité) est affiché en premier, en gras avec une étoile ; les fiches sans entité sont regroupées à part. Les **personnes sans période** (fiche non créée, ou fiche sans période de paramètres exploitable) sont aussi listées, avec la mention « Pas de période » et sans soldes.
- Un **administrateur** dispose d'une recherche rapide (🔍, Ctrl+K) : par nom RH, matricule ou e-mail, elle affiche le valideur de la personne, son délégataire du moment et ses comptes (application, Active Directory, fiches).
- **Agent** : sa synthèse et l'accès à sa fiche. **Tous les profils** (valideur, administrateur comme agent) disposent de « **Ma synthèse** » : leurs propres soldes, demandes et heures (la synthèse de l'équipe reste le « Tableau de bord »). **Valideur** : une ligne par fiche du périmètre, regroupée par responsable. **RH** (tableau de bord **réservé aux comptes administrateurs** : ni les valideurs ni les agents ne le voient, et l'API le refuse) : taux d'absence (jours d'absence ÷ capacité de travail) global, par direction / service et en arbre ; demandes en retard (plus de 3 jours) ; RCH proches de l'expiration.
- Dans l'arbre du tableau de bord RH, chaque groupe porte le **nom de l'entité** (et non celui du valideur) ; le **responsable** de l'entité est en premier, les entités de même nom sont regroupées.
- **Planning mensuel** : absences jour par jour (les jours **non validés**, d'une demande en attente, en couleur éclaircie et **pointillé**, comme dans la fiche), week-ends, jours fériés, vacances scolaires, totaux par agent ; limité au périmètre ; les agents voient leur équipe avec les **motifs masqués** (présence / absence seulement) ; un encadrant voit la **raison** pour son équipe et sa propre fiche, et la **disponibilité** (présence / absence) de ses encadrants, regroupés en tête.

## 9. Authentification

- **Agent sans compte Active Directory** : le valideur de l'agent (ou un administrateur) génère un code d'activation à usage unique, valable 7 jours, remis à l'agent avec un QR code. L'agent l'utilise avec son matricule dans la version mobile, contrôle son smartphone par un code reçu par SMS (le numéro n'est enregistré qu'à cette condition) puis choisit un mot de passe de 10 caractères au moins (lettres et chiffres). Après 5 codes erronés l'activation est verrouillée et un nouveau code doit être demandé ; un compte activé se connecte avec son matricule et son mot de passe local. L'agent peut indiquer une **adresse e-mail (facultative)** ; **sans e-mail**, la confirmation de ses demandes et de ses validations lui est envoyée **par SMS** (il en va de même d'un valideur sans e-mail : nouvelle demande, confirmation de sa décision). Le **mot de passe oublié** est possible pour les agents dont le smartphone a été contrôlé (code SMS à 6 chiffres, 10 minutes, 5 essais, 3 envois par heure ; réponse identique que le compte existe ou non) ; sinon le valideur génère un nouveau code d'activation. **« Se souvenir de moi »** garde la connexion 30 jours (jamais pour un administrateur ; coupée à la déconnexion et à tout changement de mot de passe) ; un **verrou par empreinte ou Face ID** peut protéger l'application sur le téléphone (contrôle local). Principes détaillés : `docs/ACCES_AGENTS_SANS_AD.md`.
- **Mode local** : mots de passe de l'application (8 caractères minimum). **Mode AD** : le mot de passe est celui du compte Ville ; le compte doit exister dans l'application. Les **administrateurs** gardent un mot de passe local de secours.
- L'**identifiant** de connexion est insensible aux majuscules et minuscules.
- Le bouton « Mot de passe » n'est pas proposé en mode AD (le mot de passe est celui du compte Ville, administrateurs compris). Le mot de passe local de secours d'un administrateur est **facultatif** à la création en mode AD (obligatoire en mode local).
- Les **connexions mémorisées** (« se souvenir de moi ») d'une personne sont coupées dès que son mot de passe change, que ce soit par elle, par l'activation ou la réinitialisation, ou par un administrateur. Tous les **SMS** envoyés par l'application (activation, contrôle du smartphone, réinitialisation, confirmations de demandes) sont inscrits dans le journal des e-mails, avec le numéro masqué ; le code à usage unique n'y est jamais enregistré.
- Session de 10 h ; **8 échecs en 15 minutes** par adresse bloquent les essais ; même message pour un compte inconnu et un mauvais mot de passe.
- Chaque connexion, échec, déconnexion et « se connecter en tant que » est journalisé. Un administrateur peut se connecter **en tant que** un autre compte (bandeau d'identité, tout est tracé).

## 10. Notifications

- Dans l'e-mail de demande, les dates sont en **plages** (« du 20 avril 2026 au 24 avril 2026 », week-ends sautés) et trois **boutons** sont proposés : **Valider**, **Refuser** (page de confirmation personnelle, valable 14 jours : ouvrir le lien n'enregistre rien, la décision est prise au clic et revérifiée comme dans l'application) et **Voir le calendrier d'équipe**.

- Chaque **nouvelle demande** envoie un mail au valideur **s'il a une adresse e-mail** (sinon l'envoi est journalisé « non envoyé » ; Mon équipe signale les personnes sans e-mail) ; une **relance quotidienne** liste les demandes en attente depuis plus de 3 jours.
- L'envoi automatique est **désactivé tant que l'administrateur ne l'active pas** ; un échec d'envoi n'empêche jamais l'enregistrement d'une demande ; chaque envoi est inscrit au journal des e-mails.

## 11. Données de référence (Sedit RH)

- Les agents de Sedit RH ne sont lus qu'à la demande et gardés quelques minutes en mémoire ; seuls ceux que l'on crée ou rapproche sont enregistrés.
- Le **rapprochement des matricules** se fait par nom et prénom : seules les correspondances certaines sont proposées ; les homonymes ne sont jamais rapprochés automatiquement.
- La **date d'arrivée** issue de Sedit RH n'est reprise que si elle tombe dans l'année de la fiche.
- **Nom affiché** : une personne (et en particulier un valideur) s'affiche **partout au même format « Prénom NOM »** : son nom Active Directory (remis dans cet ordre) s'il est connu, sinon son prénom et son nom de famille ; le nom RH (Sedit RH) apparaît en dessous, en petit et en italique, quand il est différent. Le nom RH reste la référence pour la recherche d'un agent et pour l'API « manager d'un agent » (`/api/v1/managers`), qui ne renvoie jamais le nom AD.
- Mon équipe signale par une alerte les personnes actives dont le **lien Active Directory est incomplet** (pas d'identifiant AD, ou pas d'adresse e-mail dans l'AD) ; « Recherche AD » les relie et enregistre leur nom AD.
- Le **manager** d'un agent est son valideur ; s'il délègue ce jour-là (absence ou période de délégation), le délégataire est indiqué en plus.

## 12. Agenda Outlook (module exchange)

- Un agent peut demander, dans « Ma synthèse », que ses absences soient **synchronisées automatiquement avec son agenda Outlook** (décochée par défaut ; personnelle).
- Chaque **jour d'absence** devient un événement **« ABSENT »** (disponibilité « Absent du bureau »), sans autre texte ; une **demi-journée** donne un événement sur le matin ou l'après-midi. Le **télétravail** devient un événement en disponibilité **« Travaille ailleurs »**.
- Les absences prises en compte sont celles du **taux d'absence** (CA, RTT, CM, CP, CT, GEM, SF, JS, JB…) ; les présences, week-ends et jours fériés ne produisent aucun événement. La synchronisation couvre **du 1er janvier de l'année en cours à la fin de l'année suivante** (les absences déjà passées de l'année sont donc reprises).
- L'agenda est mis à jour dès qu'une demande est faite, validée, refusée ou annulée ; un événement supprimé dans Outlook est recréé à la synchronisation suivante.
- Les **jours Sedit RH** affichés dans la synthèse sont les jours ouvrés (hors week-ends et jours fériés) des absences saisies dans Sedit RH sur l'année de la fiche ; ils sont informatifs et n'entrent dans aucun solde.
- Le **restant prévisionnel** d'un solde est le restant calculé comme si toutes les demandes en attente (jours, heures, cassages) étaient validées.
- Un jour **demandé** (demande en attente de validation) est indiqué « ABSENT » en disponibilité **« Provisoire »** ; une fois validé, il passe en « Absent du bureau » ; refusé ou annulé, il disparaît.
- L'application **ne modifie que les événements qu'elle a créés** ; décocher la case les retire de l'agenda ; les événements passés restent.

