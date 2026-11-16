-- 0005 — unités organisationnelles (issues de Sedit RH) et rattachement des personnes.
--
-- Le champ users.role conserve le niveau interne (administrateur, dgs … equipe, agent) utilisé par le moteur de périmètre ;
-- l'application n'expose que trois profils : Administrateur, Valideur, Agent (voir MANIFEST §14.x).

-- Unités de l'organisation RH (Direction > Service > Secteur > Équipe), recopiées depuis Sedit RH à la demande.
-- Aucune donnée personnelle : code, libellé, niveau, parent.
CREATE TABLE org_units (
    code TEXT PRIMARY KEY,
    libelle TEXT NOT NULL DEFAULT '',
    level TEXT NOT NULL,                      -- direction | service | secteur | equipe
    parent_code TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL DEFAULT 0,
    synced_at TEXT NOT NULL DEFAULT to_char(localtimestamp, 'YYYY-MM-DD HH24:MI:SS')
);
CREATE INDEX idx_org_units_parent ON org_units(parent_code);

-- Unité d'affectation de la personne, et unité qui la valide (valideurs : unité supérieure à la sienne).
ALTER TABLE users ADD COLUMN unit_code TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN validator_unit_code TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_users_unit ON users(unit_code) WHERE unit_code <> '';
