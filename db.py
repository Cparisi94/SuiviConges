# -*- coding: utf-8 -*-
"""Accès SQLite : initialisation du schéma et helpers."""
import os
import sqlite3
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "suivi-conges.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE,
    nom TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    mot_de_passe TEXT NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0,
    role TEXT NOT NULL DEFAULT 'secteur',
    parent_id INTEGER REFERENCES users(id),
    actif INTEGER NOT NULL DEFAULT 1,
    cree_le TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS user_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    target_login TEXT NOT NULL DEFAULT '',
    actor_id INTEGER,
    actor_login TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    field TEXT NOT NULL DEFAULT '',
    old_value TEXT NOT NULL DEFAULT '',
    new_value TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);
CREATE INDEX IF NOT EXISTS idx_user_audit_created ON user_audit(created_at);

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_user_id INTEGER REFERENCES users(id),
    nom TEXT NOT NULL,
    prenom TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    validator_id INTEGER REFERENCES users(id),
    year INTEGER NOT NULL DEFAULT 2027,
    params TEXT NOT NULL DEFAULT '{}',
    periods TEXT NOT NULL DEFAULT '[]',
    is_manager INTEGER NOT NULL DEFAULT 0,
    cree_le TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    modifie_le TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS cells (
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    jour INTEGER NOT NULL,
    code TEXT NOT NULL,
    PRIMARY KEY (agent_id, jour)
);

CREATE TABLE IF NOT EXISTS settings (
    cle TEXT PRIMARY KEY,
    valeur TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    year INTEGER NOT NULL,
    request_type TEXT NOT NULL DEFAULT 'absence',
    code TEXT NOT NULL,
    cells TEXT NOT NULL DEFAULT '[]',
    days REAL NOT NULL DEFAULT 0,
    hours REAL NOT NULL DEFAULT 0,
    absence_date TEXT NOT NULL DEFAULT '',
    start_time TEXT NOT NULL DEFAULT '',
    end_time TEXT NOT NULL DEFAULT '',
    valid_until TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'en_attente',
    validator_id INTEGER REFERENCES users(id),
    validator_account_name TEXT NOT NULL DEFAULT '',
    validator_manager_name TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    decision_comment TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    soumis_le TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
    decide_le TEXT,
    attachment_name TEXT NOT NULL DEFAULT '',
    attachment_file TEXT NOT NULL DEFAULT '',
    attachment_size INTEGER NOT NULL DEFAULT 0,
    attachment_mime TEXT NOT NULL DEFAULT '',
    cancel_requested_at TEXT,
    cancel_requested_by INTEGER,
    cancel_reason TEXT NOT NULL DEFAULT '',
    cancel_decided_at TEXT,
    cancel_decided_by INTEGER,
    cancel_decision_comment TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS leave_request_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES leave_requests(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id),
    comment TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS hourly_absences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    year INTEGER NOT NULL,
    absence_date TEXT NOT NULL,
    code TEXT NOT NULL,
    start_time TEXT NOT NULL DEFAULT '',
    end_time TEXT NOT NULL DEFAULT '',
    hours REAL NOT NULL DEFAULT 0,
    request_id INTEGER REFERENCES leave_requests(id) ON DELETE SET NULL,
    created_by INTEGER REFERENCES users(id),
    cree_le TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
);

CREATE INDEX IF NOT EXISTS idx_hourly_agent_date ON hourly_absences(agent_id, absence_date);
CREATE INDEX IF NOT EXISTS idx_hourly_request ON hourly_absences(request_id);
CREATE INDEX IF NOT EXISTS idx_leave_requests_agent ON leave_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_leave_requests_status ON leave_requests(status);
CREATE INDEX IF NOT EXISTS idx_leave_requests_validator ON leave_requests(validator_id);
CREATE INDEX IF NOT EXISTS idx_leave_requests_user ON leave_requests(user_id);
"""


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    # Migrations légères pour les bases existantes
    rcols = {r[1] for r in conn.execute("PRAGMA table_info(leave_requests)").fetchall()}
    request_columns = {
        "request_type": "TEXT NOT NULL DEFAULT 'absence'",
        "hours": "REAL NOT NULL DEFAULT 0",
        "absence_date": "TEXT NOT NULL DEFAULT ''",
        "start_time": "TEXT NOT NULL DEFAULT ''",
        "end_time": "TEXT NOT NULL DEFAULT ''",
        "valid_until": "TEXT NOT NULL DEFAULT ''",
        "validator_account_name": "TEXT NOT NULL DEFAULT ''",
        "validator_manager_name": "TEXT NOT NULL DEFAULT ''",
        "attachment_name": "TEXT NOT NULL DEFAULT ''",
        "attachment_file": "TEXT NOT NULL DEFAULT ''",
        "attachment_size": "INTEGER NOT NULL DEFAULT 0",
        "attachment_mime": "TEXT NOT NULL DEFAULT ''",
        "cancel_requested_at": "TEXT",
        "cancel_requested_by": "INTEGER",
        "cancel_reason": "TEXT NOT NULL DEFAULT ''",
        "cancel_decided_at": "TEXT",
        "cancel_decided_by": "INTEGER",
        "cancel_decision_comment": "TEXT NOT NULL DEFAULT ''",
    }
    for name, ddl in request_columns.items():
        if name not in rcols:
            conn.execute("ALTER TABLE leave_requests ADD COLUMN %s %s" % (name, ddl))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "role" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'secteur'")
    if "parent_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN parent_id INTEGER REFERENCES users(id)")
    if "email" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    # Les comptes administrateur existants prennent le rôle administrateur.
    conn.execute(
        "UPDATE users SET role='administrateur' "
        "WHERE admin=1 AND (role IS NULL OR role='' OR role='secteur')"
    )
    # Dimension « année » sur les fiches (bases existantes).
    acols = {r[1] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
    if "year" not in acols:
        conn.execute("ALTER TABLE agents ADD COLUMN year INTEGER NOT NULL DEFAULT 2027")
        row = conn.execute("SELECT valeur FROM settings WHERE cle='general'").fetchone()
        year = 2027
        if row:
            try:
                year = int(json.loads(row["valeur"]).get("year", 2027))
            except (ValueError, TypeError):
                pass
        conn.execute("UPDATE agents SET year=?", (year,))
    agent_columns = {
        "prenom": "TEXT NOT NULL DEFAULT ''",
        "email": "TEXT NOT NULL DEFAULT ''",
        "validator_id": "INTEGER",
        "agent_user_id": "INTEGER REFERENCES users(id)",
        "periods": "TEXT NOT NULL DEFAULT '[]'",
        "is_manager": "INTEGER NOT NULL DEFAULT 0",
    }
    for name, ddl in agent_columns.items():
        if name not in acols:
            conn.execute("ALTER TABLE agents ADD COLUMN %s %s" % (name, ddl))
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agents_agent_user ON agents(agent_user_id)"
    )
    # Anciennes fiches : sépare le dernier mot du nom en prénom et force les majuscules.
    for row in conn.execute("SELECT id, nom, prenom FROM agents").fetchall():
        nom = (row["nom"] or "").strip().upper()
        prenom = (row["prenom"] or "").strip().upper()
        if not prenom and nom:
            parts = nom.split()
            if len(parts) >= 2:
                prenom = parts[-1]
                nom = " ".join(parts[:-1])
        conn.execute("UPDATE agents SET nom=?, prenom=? WHERE id=?", (nom, prenom, row["id"]))

    # Codes d'heures : remplace CAF/RTTF par CAH/RTTH dans les bases existantes.
    row = conn.execute("SELECT valeur FROM settings WHERE cle='codes'").fetchone()
    if row:
        try:
            codes = json.loads(row["valeur"])
        except (TypeError, ValueError):
            codes = []
        changed = False
        seen = set()
        migrated = []
        for item in codes:
            code = item.get("code")
            if code in ("CB", "HS", "RC"):
                changed = True
                continue
            if code == "CAF":
                item = {"code": "CAH", "libelle": "Congé annuel en heures",
                        "color": "FFE699", "in_n": True, "in_s": False}
                changed = True
            elif code == "RTTF":
                item = {"code": "RTTH", "libelle": "RTT en heures",
                        "color": "C6E0B4", "in_n": True, "in_s": False}
                changed = True
            code = item.get("code")
            if code in seen:
                changed = True
                continue
            seen.add(code)
            migrated.append(item)
        for code, libelle, color in (
            ("CAH", "Congé annuel en heures", "FFE699"),
            ("RTTH", "RTT en heures", "C6E0B4"),
            ("RCH", "Récupération en heures", "2F75B5"),
        ):
            if code not in seen:
                migrated.append({"code": code, "libelle": libelle, "color": color,
                                 "in_n": True, "in_s": False})
                changed = True
        if changed:
            conn.execute(
                "UPDATE settings SET valeur=? WHERE cle='codes'",
                (json.dumps(migrated, ensure_ascii=False),),
            )

    # Historisation des noms valideur / responsable d'unité sur les anciennes demandes.
    rows = conn.execute(
        "SELECT r.id, r.validator_id, r.year, r.user_id, "
        "a.validator_id AS agent_validator_id, a.user_id AS agent_owner_id "
        "FROM leave_requests r JOIN agents a ON a.id=r.agent_id "
        "WHERE r.validator_account_name='' AND r.validator_manager_name=''"
    ).fetchall()
    for r in rows:
        effective = (
            r["validator_id"] or r["agent_validator_id"]
            or r["agent_owner_id"] or r["user_id"]
        )
        user = conn.execute(
            "SELECT nom, login FROM users WHERE id=?", (effective,)
        ).fetchone()
        account = ((user["nom"] or user["login"] or "") if user else "")
        manager = conn.execute(
            "SELECT nom, prenom FROM agents "
            "WHERE user_id=? AND year=? AND is_manager=1 ORDER BY id LIMIT 1",
            (effective, r["year"]),
        ).fetchone()
        manager_name = (
            ("%s %s" % (manager["nom"], manager["prenom"] or "")).strip()
            if manager else ""
        )
        conn.execute(
            "UPDATE leave_requests SET validator_account_name=?, validator_manager_name=? "
            "WHERE id=?",
            (account, manager_name, r["id"]),
        )
    conn.commit()
    conn.close()


def row_to_dict(row):
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def public_user(row):
    """Ligne user sans le hash du mot de passe."""
    d = row_to_dict(row)
    if d:
        d.pop("mot_de_passe", None)
    return d


def set_setting(db, cle, valeur):
    import json

    if not isinstance(valeur, str):
        valeur = json.dumps(valeur, ensure_ascii=False)
    db.execute(
        "INSERT INTO settings (cle, valeur) VALUES (?,?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur",
        (cle, valeur),
    )


if __name__ == "__main__":
    init_db()
    print("Base initialisée :", DB_PATH)
