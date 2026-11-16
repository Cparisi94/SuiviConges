-- Délégation automatique activée par défaut pour tous les valideurs (décision du 2026-11-16) :
-- quand un valideur est absent (journée complète posée dans sa fiche), son propre valideur est prévenu et trace ses validations.
-- Les valideurs peuvent la désactiver dans « Délégation » ; les nouveaux comptes (et les agents promus valideurs) l'ont activée.
ALTER TABLE users ALTER COLUMN delegate_auto SET DEFAULT 1;
UPDATE users SET delegate_auto = 1 WHERE delegate_auto = 0;
