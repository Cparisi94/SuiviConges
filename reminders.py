# -*- coding: utf-8 -*-
"""Relances automatiques des demandes en attente.

Les relances e-mail ne partent que si mail.json est active. Une relance
maximale par jour est envoyee a chaque valideur concerne.
"""
import datetime as dt
import os
import sqlite3
import threading
import time

import mailer
from db import DB_PATH

DEFAULT_DAYS = 3
DEFAULT_INTERVAL = 6 * 3600


def _log(message):
    line = "%s [reminder] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    print(line)
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "reminder.log"),
                  "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _get_setting(conn, key):
    row = conn.execute("SELECT valeur FROM settings WHERE cle=?", (key,)).fetchone()
    return row[0] if row else ""


def _set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings (cle, valeur) VALUES (?,?) "
        "ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur",
        (key, value),
    )


def pending_requests(conn, days=DEFAULT_DAYS):
    return conn.execute(
        "SELECT r.id, r.code, r.soumis_le, r.cree_le, r.validator_id, "
        "TRIM(a.nom || ' ' || COALESCE(a.prenom, '')) AS agent_nom, "
        "v.email AS validator_email, v.nom AS validator_nom, v.login AS validator_login "
        "FROM leave_requests r "
        "JOIN agents a ON a.id=r.agent_id "
        "LEFT JOIN users v ON v.id=r.validator_id "
        "WHERE r.status IN ('en_attente','annulation_demandee') "
        "AND COALESCE(r.soumis_le, r.cree_le) < datetime('now', ?) "
        "ORDER BY v.id, r.soumis_le",
        ("-%d days" % int(days),),
    ).fetchall()


def send_pending_reminders(days=DEFAULT_DAYS):
    """Envoie une relance quotidienne aux valideurs ayant des demandes anciennes."""
    if not mailer.load_config():
        return {"sent": 0, "disabled": True}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    today = dt.date.today().isoformat()
    try:
        if _get_setting(conn, "last_pending_reminder_date") == today:
            return {"sent": 0, "already_sent": True}
        rows = pending_requests(conn, days)
        groups = {}
        for row in rows:
            key = row["validator_id"] or row["validator_login"] or row["validator_nom"]
            groups.setdefault(key, []).append(row)
        sent = 0
        for group in groups.values():
            first = group[0]
            email = (first["validator_email"] or "").strip()
            if not email:
                continue
            name = first["validator_nom"] or first["validator_login"] or "valideur"
            lines = [
                "Bonjour,",
                "",
                "Les demandes suivantes sont en attente depuis plus de %s jours :" % days,
                "",
            ]
            for row in group:
                lines.append("- %s — %s — demande du %s" % (
                    row["agent_nom"] or "Agent",
                    row["code"] or "",
                    str(row["soumis_le"] or row["cree_le"] or "")[:10],
                ))
            lines.extend([
                "",
                "Merci de les traiter dans l'outil de suivi des congés.",
                "",
                "Cordialement,",
                "Outil de suivi des congés",
            ])
            ok, error = mailer.send_mail(
                email,
                "[Suivi congés] Relance : %s demande(s) en attente" % len(group),
                "\n".join(lines),
            )
            if ok:
                sent += 1
            else:
                _log("relance non envoyée à %s : %s" % (email, error))
        _set_setting(conn, "last_pending_reminder_date", today)
        conn.commit()
        _log("%s relance(s) envoyée(s) pour %s demande(s)" % (sent, len(rows)))
        return {"sent": sent, "requests": len(rows)}
    finally:
        conn.close()


def start_reminder_scheduler(interval=DEFAULT_INTERVAL):
    if os.environ.get("CONGES_DISABLE_REMINDERS") == "1":
        return None

    def run():
        while True:
            try:
                send_pending_reminders()
            except Exception as exc:  # noqa: BLE001 - ne doit pas bloquer l'app
                _log("échec de la relance automatique : %s" % exc)
            time.sleep(max(300, int(interval)))

    thread = threading.Thread(target=run, name="conges-reminders", daemon=True)
    thread.start()
    _log("planificateur de relances démarré")
    return thread


if __name__ == "__main__":
    print(send_pending_reminders())
