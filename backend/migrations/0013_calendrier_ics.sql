-- 0013 — abonnement iCalendar (ICS) : l'agent ajoute à l'agenda de son téléphone un lien personnel et secret qui publie ses congés
-- (validés ou en attente). Un seul lien actif par personne ; seul le HACHÉ du jeton est conservé (le lien complet n'est montré qu'à sa création).
CREATE TABLE calendar_tokens (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT '',         -- AAAA-MM-JJ HH:MM:SS
    last_used_at TEXT NOT NULL DEFAULT ''        -- dernière lecture du flux par le téléphone ('' = jamais)
);
