-- 0012 — nom Active Directory de la personne.
-- Le nom RH (Sedit RH) reste dans users.nom / nom_famille / prenom ; le nom AD (displayName, ex. « Sofia Abdiche ») est celui
-- affiché par défaut dans l'application, le nom RH apparaissant en dessous en italique quand il diffère.
ALTER TABLE users ADD COLUMN nom_ad TEXT NOT NULL DEFAULT '';
