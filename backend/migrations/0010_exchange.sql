-- 0010 — module « exchange » : synchronisation des absences avec l'agenda Outlook de l'agent (API Microsoft Graph).
--
-- Chaque agent choisit dans « Ma synthèse » s'il veut la synchronisation (users.exchange_sync, désactivée par défaut).
-- Pour chaque jour (ou demi-journée) d'absence, un événement « ABSENT » est créé dans son agenda ; le télétravail devient
-- un événement « Travaille ailleurs ». La table exchange_events retient les événements créés pour pouvoir les mettre à jour
-- ou les supprimer (changement de la fiche, désactivation).
ALTER TABLE users ADD COLUMN exchange_sync INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN exchange_synced_at TEXT NOT NULL DEFAULT '';      -- dernière synchronisation réussie (AAAA-MM-JJ HH:MM:SS)
ALTER TABLE users ADD COLUMN exchange_error TEXT NOT NULL DEFAULT '';          -- dernière erreur (vide si tout va bien)

CREATE TABLE exchange_events (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day TEXT NOT NULL,                       -- AAAA-MM-JJ
    part TEXT NOT NULL,                      -- J journée entière, M matin, A après-midi
    kind TEXT NOT NULL,                      -- ABSENT ou TT
    event_id TEXT NOT NULL,                  -- identifiant de l'événement dans Outlook
    PRIMARY KEY (user_id, day, part)
);
