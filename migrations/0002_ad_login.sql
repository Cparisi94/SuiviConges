-- 0002 — identifiant Active Directory des comptes.
-- Vide = l'identifiant de l'application est aussi l'identifiant AD.
ALTER TABLE users ADD COLUMN ad_login TEXT NOT NULL DEFAULT '';
