-- 0016 — Absences de Sedit RH (CM, GEM, CT, CP, SF) conservées en base.
-- Elles sont relues dans Sedit RH à chaque affichage d'un planning ou d'un compteur et remplacent alors ce qui était stocké pour la personne et l'année ;
-- si Sedit RH ne répond pas, la dernière lecture sert (les compteurs et les déductions de RTT / sujétions restent calculables).
CREATE TABLE absences_rh (
    id SERIAL PRIMARY KEY,
    matricule TEXT NOT NULL,
    annee INTEGER NOT NULL,
    code TEXT NOT NULL,
    libelle TEXT NOT NULL DEFAULT '',
    debut DATE NOT NULL,
    fin DATE NOT NULL,
    maj_le TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX absences_rh_mat_idx ON absences_rh (matricule, annee);
