-- 0015 — « Se souvenir de moi » : connexion persistante (30 jours) par jeton aléatoire stocké dans un cookie HttpOnly.
-- Seul le HACHÉ du jeton est conservé ; il est supprimé à la déconnexion et à tout changement de mot de passe.
CREATE TABLE remember_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    cree_le TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expire_le TIMESTAMP NOT NULL,
    derniere_utilisation TIMESTAMP,
    appareil TEXT NOT NULL DEFAULT ''
);
CREATE INDEX remember_tokens_user_idx ON remember_tokens (user_id);
