-- 0011 — cache du solde de CET lu dans Sedit RH.
-- Un solde est conservé ici (et en mémoire) : la page le reçoit tout de suite, même après un redémarrage ou si Sedit RH est en panne,
-- et il est recalculé en arrière-plan quand il a plus de 10 minutes.
CREATE TABLE sedit_cet_cache (
    matricule TEXT PRIMARY KEY,
    solde DOUBLE PRECISION NOT NULL DEFAULT 0,       -- solde en jours (solde initial + dépôts - retraits des comptes ouverts)
    comptes INTEGER NOT NULL DEFAULT 0,              -- nombre de comptes ouverts
    has_cet INTEGER NOT NULL DEFAULT 0,              -- 0 : l'agent n'a pas de CET (résultat négatif conservé aussi)
    fetched_epoch DOUBLE PRECISION NOT NULL          -- instant de la lecture (secondes depuis 1970)
);
