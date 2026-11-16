-- 0008 — unités créées localement (absentes de Sedit RH) et responsable d'une unité.
-- Une unité locale (ex. « Numérique éducatif », « Cellule administrative et financière ») n'est jamais écrasée par la synchronisation Sedit RH.
ALTER TABLE org_units ADD COLUMN local INTEGER NOT NULL DEFAULT 0;
ALTER TABLE org_units ADD COLUMN head_user_id INTEGER;          -- le responsable de l'unité (un compte)
