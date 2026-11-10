# -*- coding: utf-8 -*-
"""Notifications e-mail pour les demandes de congés.

La configuration SMTP est lue dans mail.json (non exposé par le serveur web).
Si le fichier est absent, désactivé ou incomplet, aucun e-mail n'est envoyé.
"""
import datetime as dt
import json
import os
import smtplib
import ssl
import threading
from email.message import EmailMessage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "mail.json")
LOG_PATH = os.path.join(BASE_DIR, "mail.log")

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _log(message):
    line = "%s [mail] %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    print(line)


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return None
    if not cfg.get("enabled"):
        return None
    if not cfg.get("host") or not cfg.get("from"):
        return None
    return cfg


def _format_days(days):
    return ("%g" % float(days)).replace(".", ",")


def cell_label(key, year):
    """Libellé d'une demi-journée à partir de la clé (mois*1000 + jour*10 + 0/1)."""
    try:
        key = int(key)
    except (TypeError, ValueError):
        return str(key)
    month = key // 1000
    day = (key % 1000) // 10
    half = key % 10
    if not (1 <= month <= 12):
        return str(key)
    return "%d %s %d — %s" % (
        day, MOIS[month - 1], int(year), "matin" if half == 0 else "après-midi"
    )


def _deliver(cfg, to, subject, body):
    msg = EmailMessage()
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    host = cfg["host"]
    ssl_enabled = bool(cfg.get("ssl"))
    port = int(cfg.get("port") or (465 if ssl_enabled else 25))
    timeout = int(cfg.get("timeout") or 15)

    if ssl_enabled:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=timeout) as smtp:
            if cfg.get("username"):
                smtp.login(cfg["username"], cfg.get("password") or "")
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=timeout) as smtp:
        smtp.ehlo()
        if cfg.get("starttls"):
            context = ssl.create_default_context()
            smtp.starttls(context=context)
            smtp.ehlo()
        if cfg.get("username"):
            smtp.login(cfg["username"], cfg.get("password") or "")
        smtp.send_message(msg)


def send_mail(to, subject, body):
    """Envoi synchrone. Retourne (ok, message_erreur)."""
    cfg = load_config()
    if not cfg:
        return False, "Configuration mail absente ou désactivée (mail.json)"
    to = (to or "").strip()
    if not to:
        return False, "Aucune adresse e-mail de destinataire"
    try:
        _deliver(cfg, to, subject, body)
    except Exception as exc:  # noqa: BLE001 — l'échec mail ne doit pas bloquer l'app
        _log("échec pour %s : %s" % (to, exc))
        return False, str(exc)
    _log("envoyé à %s" % to)
    return True, ""


def notify_validator(validator_email, validator_name, agent_name, code, code_label,
                     cells, year, days, comment, fiche_id, request_id):
    """Prévient le valideur d'une nouvelle demande (en arrière-plan)."""
    cfg = load_config()
    if not cfg:
        return
    to = (validator_email or "").strip()
    if not to:
        _log("aucune adresse e-mail pour le valideur %s (demande %s)" % (
            validator_name or "?", request_id))
        return

    base = (cfg.get("base_url") or "").rstrip("/")
    fiche_url = "%s/#/agent/%s" % (base, fiche_id) if base else ""
    requests_url = "%s/#/requests" % base if base else ""

    lines = [
        "Bonjour,",
        "",
        "%s a soumis une demande de congé." % agent_name,
        "",
        "Code : %s (%s)" % (code_label, code),
        "Demi-journées :",
    ]
    for key in sorted(cells):
        lines.append("  - %s" % cell_label(key, year))
    lines.extend([
        "",
        "Nombre de jours : %s" % _format_days(days),
        "Commentaire : %s" % (comment or "—"),
    ])
    if fiche_url:
        lines.extend(["", "Fiche : %s" % fiche_url])
    if requests_url:
        lines.append("Demandes à valider : %s" % requests_url)
    lines.extend([
        "",
        "Cette demande est en attente de votre validation.",
        "",
        "Cordialement,",
        "Outil de suivi des congés",
    ])

    subject = "[Suivi congés] Demande de %s — %s" % (agent_name, code_label)
    body = "\n".join(lines)
    threading.Thread(
        target=send_mail, args=(to, subject, body), daemon=True
    ).start()
