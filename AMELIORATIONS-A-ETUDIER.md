# Améliorations à étudier — Outil congés

**Date de mise en note :** 06/11/2026  
**Statut :** réflexions conservées pour plus tard — aucune décision ni implémentation  
**Périmètre :** prototype sur le port **5567** uniquement. Le **5566** ne doit pas être modifié.

---

## Contexte actuel

- Hiérarchie en place : **Administrateur > DGS > DGA > Direction > Service > Secteur > Unité > Équipe > Agent**.
- Gestion des CA/RTT en heures, déclarations RCH, soldes d’heures et tableau détaillé.
- Validation hiérarchique, historique des demandes, gestion des propriétaires de fiches.
- Gestion des comptes et des identifiants par l’administrateur.
- Notifications e-mail prévues mais désactivées, en attente des paramètres SMTP.

---

## Priorité 1 — Sécurité et fiabilité

- [ ] Remplacer la suppression définitive des comptes par une **désactivation / archivage**, afin de conserver l’historique des fiches.
- [ ] Ajouter un **journal d’audit des comptes** : création, changement de login, rôle, responsable, mot de passe, activation/désactivation, suppression.
- [ ] Empêcher les **cycles hiérarchiques** : un responsable ne doit pas pouvoir être placé sous l’un de ses descendants.
- [ ] Renforcer les règles d’identifiants et mots de passe :
  - unicité sans distinction de casse ;
  - longueur minimale ;
  - changement obligatoire à la première connexion ;
  - expiration de session.
- [ ] Supprimer ou neutraliser les **comptes de démonstration** avant mise en production.
- [ ] Mettre en place des **sauvegardes automatiques** de la base SQLite avec rotation et test de restauration.

---

## Priorité 2 — Circuit de validation et notifications

- [ ] Notifications **e-mail et/ou in-app** : nouvelle demande, validation, refus, annulation, déclaration RCH.
- [ ] **Alerte d’expiration des heures RCH** : prévenir l’agent et son valideur 30 jours avant l’échéance des 6 mois.
- [ ] **Délégation de validation** : permettre à un valideur absent de désigner un remplaçant temporaire.
- [ ] **Relances automatiques** pour les demandes en attente depuis plusieurs jours.
- [ ] **Pièce jointe** pour les déclarations RCH, si un justificatif est nécessaire.
- [ ] Étudier une **validation multi-niveaux séquentielle** si une demande doit passer obligatoirement par plusieurs valideurs successifs.

---

## Priorité 3 — Administration et exploitation

- [ ] **Import CSV / annuaire** des comptes pour éviter la création manuelle.
- [ ] **Organigramme visuel** de la hiérarchie.
- [ ] **Recherche, filtres et pagination** dans Utilisateurs et Demandes.
- [ ] **Actions groupées** : changer un responsable, désactiver plusieurs comptes, dupliquer des fiches.
- [ ] **Exports Excel/CSV** : soldes, demandes, heures, historique, absences par service.
- [ ] **Tableau de bord RH** : absences par direction/service, taux d’absence, demandes en retard, heures RCH à échéance.

---

## Priorité 4 — Évolutions plus lourdes

- [ ] Rendre les **niveaux hiérarchiques configurables** par l’administrateur, plutôt que codés en dur.
- [ ] Mettre en place une **matrice de droits** plus fine : consulter / valider / gérer les comptes.
- [ ] Améliorer le **responsive mobile** et l’accessibilité.
- [ ] Ajouter des **tests automatisés de non-régression** sur les règles de congés, la hiérarchie et les compteurs d’heures.

---

## Prochaines étapes recommandées

1. Audit des comptes + archivage au lieu de suppression.
2. Notifications e-mail/in-app.
3. Alerte d’expiration des heures RCH.
4. Sauvegardes automatiques + tests de non-régression.
5. Import des utilisateurs, organigramme, exports et tableau de bord RH.

---

## Notes

- Ne pas oublier de **sauvegarder la base** avant toute migration ou modification structurelle.
- Les fonctionnalités validées sur le prototype devront être recettées avant un portage sur le **5566**.
- Ce document est une liste de réflexions : il ne constitue pas un engagement de planning.


---

## Mise à jour du 10/11/2026 — éléments réalisés

- [x] Journal d’audit des comptes (création, login, rôle, responsable, mot de passe, activation/désactivation, suppression).
- [x] Tests automatisés de non-régression (python -m unittest discover -s tests -v).
- [x] Sauvegardes automatiques SQLite avec rotation et vérification de restauration.
- [x] Alerte d’expiration des heures RCH à 30 jours.
- [x] Relances automatiques des demandes en attente (bandeau in-app et e-mail si SMTP actif).
- [x] Recherche, filtres et pagination dans Utilisateurs et Demandes.
- [x] Tableau de bord RH (absences par direction/service, taux, retards, RCH à échéance).
