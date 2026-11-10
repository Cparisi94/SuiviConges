# -*- coding: utf-8 -*-
"""Journaux d'administration : connexions et e-mails (écriture, consultation filtrée, purge).

L'écriture d'un journal ne doit JAMAIS faire échouer l'opération qu'elle trace : toute erreur est ignorée
(et signalée dans les logs du serveur).
"""
import json
import logging

from flask import has_request_context, request

from db import get_db, row_to_dict

log = logging.getLogger(__name__)
DEFAULT_RETENTION = {"connexions_jours": 365, "emails_jours": 365}


def client_info():
    if not has_request_context():
        return "", ""
    return (request.remote_addr or ""), (request.headers.get("User-Agent") or "")[:200]


def log_login(event, login="", user_id=None, success=True, reason="", method=""):
    """Journalise une connexion, un échec, une déconnexion ou un « en tant que »."""
    try:
        ip, agent = client_info()
        db = get_db()
        db.execute(
            "INSERT INTO login_logs (event, login, user_id, success, reason, method, ip, user_agent) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (event, (login or "")[:120], user_id, 1 if success else 0, reason, method, ip, agent),
        )
        db.commit()
        db.close()
    except Exception:  # noqa: BLE001
        log.exception("Journal des connexions : écriture impossible")


def log_mail(to_addr, subject, template, status, error="", body="", request_id=None):
    try:
        db = get_db()
        db.execute(
            "INSERT INTO mail_logs (to_addr, subject, template, status, error, body, request_id) "
            "VALUES (?,?,?,?,?,?,?)",
            ((to_addr or "")[:200], (subject or "")[:300], template or "", status, (error or "")[:500],
             (body or "")[:20000], request_id),
        )
        db.commit()
        db.close()
    except Exception:  # noqa: BLE001
        log.exception("Journal des e-mails : écriture impossible")


# --------------------------------------------------------------------------- #
#  Consultation (administrateur)
# --------------------------------------------------------------------------- #
def _where(filters):
    clauses, params = [], []
    for sql, value in filters:
        if value not in (None, ""):
            clauses.append(sql)
            params.extend(value if isinstance(value, list) else [value])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def query(table, columns, filters, limit, offset):
    where, params = _where(filters)
    db = get_db()
    total = db.execute("SELECT COUNT(*) AS c FROM %s%s" % (table, where), params).fetchone()["c"]
    rows = db.execute(
        "SELECT %s FROM %s%s ORDER BY id DESC LIMIT ? OFFSET ?" % (columns, table, where),
        params + [limit, offset],
    ).fetchall()
    db.close()
    return [row_to_dict(r) for r in rows], total


# --------------------------------------------------------------------------- #
#  Conservation
# --------------------------------------------------------------------------- #
def retention():
    db = get_db()
    row = db.execute("SELECT valeur FROM settings WHERE cle='journaux'").fetchone()
    db.close()
    try:
        stored = json.loads(row["valeur"]) if row else {}
    except ValueError:
        stored = {}
    return {k: int(stored.get(k) or v) for k, v in DEFAULT_RETENTION.items()}


def save_retention(connexions_jours, emails_jours):
    db = get_db()
    db.execute(
        "INSERT INTO settings (cle, valeur) VALUES ('journaux', ?) ON CONFLICT (cle) DO UPDATE SET valeur=excluded.valeur",
        (json.dumps({"connexions_jours": connexions_jours, "emails_jours": emails_jours}),),
    )
    db.commit()
    db.close()


def purge():
    """Supprime les entrées plus anciennes que la durée de conservation. Retourne (connexions, emails)."""
    keep = retention()
    db = get_db()
    a = db.execute(
        "DELETE FROM login_logs WHERE at < to_char(localtimestamp - CAST(? AS interval), 'YYYY-MM-DD HH24:MI:SS')",
        ("%d days" % keep["connexions_jours"],),
    ).rowcount
    b = db.execute(
        "DELETE FROM mail_logs WHERE at < to_char(localtimestamp - CAST(? AS interval), 'YYYY-MM-DD HH24:MI:SS')",
        ("%d days" % keep["emails_jours"],),
    ).rowcount
    db.commit()
    db.close()
    return a, b
