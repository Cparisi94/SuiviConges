-- 0006 — identité de la personne (nom de famille et prénom séparés), pour créer la fiche congés plus tard.
-- Une personne peut exister sans fiche : la fiche naît quand on définit sa première période de paramètres.
ALTER TABLE users ADD COLUMN nom_famille TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN prenom TEXT NOT NULL DEFAULT '';
UPDATE users SET nom_famille = a.nom, prenom = a.prenom FROM agents a WHERE a.agent_user_id = users.id;
