-- 0014 — activation d'un compte sans Active Directory (code remis par la DRH ou le valideur, puis SMS de contrôle du smartphone).
-- Seuls des HACHÉS sont conservés (code d'activation, code SMS) ; le code d'activation n'est montré qu'à sa création.
ALTER TABLE users ADD COLUMN mobile TEXT NOT NULL DEFAULT '';                       -- smartphone de l'agent, contrôlé par SMS (format 06XXXXXXXX)
ALTER TABLE users ADD COLUMN mobile_verifie_le TIMESTAMP;

CREATE TABLE activations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    cree_par INTEGER REFERENCES users(id) ON DELETE SET NULL,
    cree_le TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expire_le TIMESTAMP NOT NULL,
    utilise_le TIMESTAMP,                       -- activation terminée (mot de passe choisi)
    annule_le TIMESTAMP,                        -- remplacée par un nouveau code, ou verrouillée après trop d'essais
    essais INTEGER NOT NULL DEFAULT 0,          -- essais de code d'activation erronés
    etape TEXT NOT NULL DEFAULT 'code',         -- code -> sms -> motdepasse
    mobile_attente TEXT NOT NULL DEFAULT '',    -- numéro saisi, en attente de contrôle
    otp_hash TEXT NOT NULL DEFAULT '',
    otp_expire TIMESTAMP,
    otp_envois INTEGER NOT NULL DEFAULT 0,
    otp_dernier_envoi TIMESTAMP,
    otp_essais INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX activations_user_idx ON activations (user_id);
